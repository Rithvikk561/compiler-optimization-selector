"""
moo/adaptive/learner.py — Week 11: DQN learning/update mechanism.

Implements the genuine adaptive learning mechanism for Week 11.

The DQN architecture (from ml_optimizer.py) is reused directly — not
reimplemented.  The learner:

1.  Loads experience records from a ReplayBuffer.
2.  Converts them to (state, action_idx, reward) training tuples.
3.  Performs a Q-learning update on the DQN using the existing architecture.
4.  Saves a candidate model artifact with a ModelVersionInfo companion file.

Safety boundaries
-----------------
* The production model (ml_optimizer_model.pth) is NEVER touched.
* Candidate models land in a separate candidate_models/ directory.
* Each candidate gets a unique name (model_id) with a version number.
* ModelVersionInfo is written alongside each .pth file for auditability.
* Loading the production model is read-only (weights_only=True).
* Promotion of a candidate to production is NOT implemented here.

Determinism
-----------
* A random seed can be supplied for reproducible training.
* Shuffling of experiences for training is done via seeded RNG.
* PyTorch manual_seed is set when a seed is provided.

Architecture preservation
-------------------------
* DQN(input_dim=8, output_dim=len(ACTIONS)) — same as ml_optimizer.py.
* Loss function: MSELoss — same as ml_optimizer.py.
* Optimizer: Adam lr=0.001 — same as ml_optimizer.py.
* Q-learning target: reward (single-step, terminal-state style) — same
  as ml_optimizer.py's simplified Q-update.
* No new ML architecture is introduced.

Torch availability guard
------------------------
If torch is not available, DQNLearner degrades gracefully:
  - from_experiences() will raise ImportError with a clear message.
  - All other methods operate on metadata only.
"""

from __future__ import annotations

import json
import math
import os
import random
from typing import Optional

from .schema import (
    ADAPTIVE_SCHEMA_VERSION,
    ModelVersionInfo,
    make_timestamp,
)
from .storage import ReplayBuffer


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DQN_INPUT_DIM = 8      # must match ml_optimizer.DQN input
_CANDIDATE_MODEL_DIR = "candidate_models"
_META_SUFFIX = "_meta.json"


# ---------------------------------------------------------------------------
# Helpers to resolve ACTIONS and DQN
# ---------------------------------------------------------------------------

def _get_actions() -> list[str]:
    """Load ACTIONS from ml_optimizer.py (same as the rest of the project)."""
    try:
        from ml_optimizer import ACTIONS  # type: ignore[import]
        return list(ACTIONS)
    except Exception as exc:
        raise ImportError(
            f"Cannot import ACTIONS from ml_optimizer.py: {exc}"
        ) from exc


def _get_dqn_class():
    """Return the DQN class from ml_optimizer.py."""
    try:
        from ml_optimizer import DQN  # type: ignore[import]
        return DQN
    except Exception as exc:
        raise ImportError(
            f"Cannot import DQN from ml_optimizer.py: {exc}"
        ) from exc


def _get_torch():
    """Return the torch module, raising ImportError if unavailable."""
    try:
        import torch
        return torch
    except ImportError as exc:
        raise ImportError(
            "PyTorch (torch) is required for DQNLearner training. "
            "Install it with: pip install torch"
        ) from exc


# ---------------------------------------------------------------------------
# DQNLearner
# ---------------------------------------------------------------------------

class DQNLearner:
    """
    Adaptive learning component for the existing DQN optimizer.

    Consumes ExperienceRecord objects from a ReplayBuffer and performs
    Q-learning updates on the DQN architecture from ml_optimizer.py.
    Saves the result as a candidate model artifact — NOT the production model.

    Parameters
    ----------
    candidate_dir
        Directory where candidate model files are written.
        Defaults to a 'candidate_models/' subdirectory alongside this file.

    seed
        Random seed for reproducible training.  Affects:
          - experience shuffling order
          - torch.manual_seed (if torch is available)

    learning_rate
        Adam optimizer learning rate.  Default 0.001 (same as ml_optimizer.py).

    epochs
        Number of training passes over the experience batch.  Default 5.

    source_model_path
        If provided, the DQN is initialized from this .pth file instead of
        random weights.  Must be the PRODUCTION model path or a previous
        candidate path.  Never overwritten by this class.
    """

    def __init__(
        self,
        *,
        candidate_dir: Optional[str] = None,
        seed: Optional[int] = None,
        learning_rate: float = 0.001,
        epochs: int = 5,
        source_model_path: Optional[str] = None,
    ) -> None:
        if candidate_dir is None:
            candidate_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                _CANDIDATE_MODEL_DIR,
            )
        self._candidate_dir = os.path.abspath(candidate_dir)
        os.makedirs(self._candidate_dir, exist_ok=True)

        self._seed = seed
        self._learning_rate = learning_rate
        self._epochs = epochs
        self._source_model_path = source_model_path

        # State set after a successful learn() call
        self._last_model_version_info: Optional[ModelVersionInfo] = None
        self._last_candidate_path: Optional[str] = None

    # ----------------------------------------------------------------
    # Public properties
    # ----------------------------------------------------------------

    @property
    def candidate_dir(self) -> str:
        return self._candidate_dir

    @property
    def last_model_version_info(self) -> Optional[ModelVersionInfo]:
        """ModelVersionInfo from the most recent learn() call, or None."""
        return self._last_model_version_info

    @property
    def last_candidate_path(self) -> Optional[str]:
        """Path to the candidate .pth file from the most recent learn()."""
        return self._last_candidate_path

    # ----------------------------------------------------------------
    # Public: learn from a replay buffer
    # ----------------------------------------------------------------

    def learn(
        self,
        buffer: ReplayBuffer,
        *,
        min_experiences: int = 1,
        sample_size: Optional[int] = None,
        reward_config_id: str = "default_v1",
        model_version: int = 1,
        source_model_id: Optional[str] = None,
    ) -> ModelVersionInfo:
        """
        Train the DQN on experiences from a ReplayBuffer.

        Parameters
        ----------
        buffer
            ReplayBuffer containing validated ExperienceRecords.

        min_experiences
            If fewer than this many experiences are in the buffer,
            raise ValueError (refuse to train on an empty / tiny batch).

        sample_size
            Number of experiences to sample for training.
            If None, all buffer contents are used.

        reward_config_id
            Identifier of the reward config used for the reward values
            in the buffer.  Stored in ModelVersionInfo for auditability.

        model_version
            Integer version tag for the candidate model artifact.

        source_model_id
            model_id of the starting checkpoint (None for random init).

        Returns
        -------
        ModelVersionInfo for the saved candidate model.

        Raises
        ------
        ImportError  : if torch is not available
        ValueError   : if buffer has fewer than min_experiences
        RuntimeError : if model saving fails
        """
        torch = _get_torch()
        ACTIONS = _get_actions()
        DQN = _get_dqn_class()

        # --- Seed ---
        if self._seed is not None:
            torch.manual_seed(self._seed)
            random.seed(self._seed)

        # --- Gather experiences ---
        if len(buffer) < min_experiences:
            raise ValueError(
                f"ReplayBuffer has {len(buffer)} experiences; "
                f"need at least {min_experiences}"
            )

        if sample_size is not None and sample_size > 0:
            experiences = buffer.sample(sample_size, seed=self._seed)
        else:
            experiences = buffer.sample_all()

        if not experiences:
            raise ValueError("No experiences available for training")

        # --- Build (state, action_idx, reward) tuples ---
        action_index_map = {a: i for i, a in enumerate(ACTIONS)}
        training_tuples: list[tuple] = []

        for exp in experiences:
            feats = [exp.ir_features.get(k, 0.0) for k in _canonical_feature_order()]
            action_idx = action_index_map.get(exp.selected_action, -1)
            if action_idx < 0:
                continue  # action not in ACTIONS — skip
            reward = exp.reward
            if reward is None or not math.isfinite(reward):
                continue  # no valid reward — skip
            training_tuples.append((feats, action_idx, reward))

        if not training_tuples:
            raise ValueError(
                "No valid (state, action, reward) tuples could be built "
                "from the provided experiences. "
                "Check that selected_action values are in ACTIONS and rewards are finite."
            )

        # --- Initialize DQN ---
        n_actions = len(ACTIONS)
        model = DQN(_DQN_INPUT_DIM, n_actions)

        if self._source_model_path and os.path.isfile(self._source_model_path):
            try:
                state_dict = torch.load(
                    self._source_model_path, weights_only=True
                )
                model.load_state_dict(state_dict)
            except Exception as exc:
                # Continue with random weights rather than aborting
                pass

        optimizer = torch.optim.Adam(model.parameters(), lr=self._learning_rate)
        criterion = torch.nn.MSELoss()
        model.train()

        # Shuffle training tuples reproducibly
        rng = random.Random(self._seed)
        rng.shuffle(training_tuples)

        # --- Training loop ---
        epoch_losses: list[float] = []

        for epoch in range(self._epochs):
            epoch_loss = 0.0
            for feats, action_idx, reward in training_tuples:
                state = torch.FloatTensor(feats)
                q_values = model(state)
                target_q = q_values.clone().detach()
                target_q[action_idx] = float(reward)

                loss = criterion(q_values, target_q)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                epoch_loss += loss.item()

            if training_tuples:
                epoch_losses.append(epoch_loss / len(training_tuples))

        mean_loss = (sum(epoch_losses) / len(epoch_losses)) if epoch_losses else None

        # --- Save candidate model ---
        model.eval()
        now = make_timestamp()
        compact_ts = now.replace(":", "").replace("-", "").replace("+", "")[:15]
        model_id = f"candidate_v{model_version}_{compact_ts}"
        pth_filename = f"{model_id}.pth"
        pth_path = os.path.join(self._candidate_dir, pth_filename)

        try:
            torch.save(model.state_dict(), pth_path)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to save candidate model to {pth_path}: {exc}"
            ) from exc

        # --- Build and save ModelVersionInfo ---
        mean_reward = (
            sum(t[2] for t in training_tuples) / len(training_tuples)
            if training_tuples else None
        )
        exp_ids = [e.experience_id for e in experiences]

        mvi = ModelVersionInfo(
            schema_version=ADAPTIVE_SCHEMA_VERSION,
            model_version=model_version,
            model_id=model_id,
            created_at=now,
            source_model_id=source_model_id or (
                os.path.basename(self._source_model_path)
                if self._source_model_path else None
            ),
            experience_count=len(training_tuples),
            experience_id_first=exp_ids[0] if exp_ids else None,
            experience_id_last=exp_ids[-1] if exp_ids else None,
            training_epochs=self._epochs,
            mean_loss=mean_loss,
            mean_reward=mean_reward,
            reward_config_id=reward_config_id,
            dqn_input_dim=_DQN_INPUT_DIM,
            dqn_output_dim=n_actions,
            is_production=False,
            notes=[
                f"Trained with {len(training_tuples)} experience tuples",
                f"Learning rate: {self._learning_rate}",
                f"Epochs: {self._epochs}",
            ],
        )

        meta_path = pth_path.replace(".pth", _META_SUFFIX)
        try:
            with open(meta_path, "w", encoding="utf-8") as fh:
                json.dump(mvi.to_dict(), fh, indent=2)
        except OSError as exc:
            # Non-fatal: model is saved, metadata is supplemental
            mvi.notes.append(f"WARNING: meta file could not be written: {exc}")

        self._last_model_version_info = mvi
        self._last_candidate_path = pth_path

        return mvi

    # ----------------------------------------------------------------
    # Public: list candidate models
    # ----------------------------------------------------------------

    def list_candidates(self) -> list[ModelVersionInfo]:
        """
        Return ModelVersionInfo for all candidate models in candidate_dir.

        Models are returned in creation order (by model_version ascending).
        Returns an empty list if the directory is empty or inaccessible.
        """
        results: list[ModelVersionInfo] = []
        try:
            for fname in sorted(os.listdir(self._candidate_dir)):
                if not fname.endswith(_META_SUFFIX):
                    continue
                meta_path = os.path.join(self._candidate_dir, fname)
                try:
                    with open(meta_path, "r", encoding="utf-8") as fh:
                        d = json.load(fh)
                    mvi = ModelVersionInfo.from_dict(d)
                    results.append(mvi)
                except Exception:
                    pass
        except OSError:
            pass
        results.sort(key=lambda m: m.model_version)
        return results

    # ----------------------------------------------------------------
    # Public: get candidate path by model_id
    # ----------------------------------------------------------------

    def get_candidate_path(self, model_id: str) -> Optional[str]:
        """
        Return the path to the .pth file for the given model_id, or None.
        """
        pth_path = os.path.join(self._candidate_dir, f"{model_id}.pth")
        if os.path.isfile(pth_path):
            return pth_path
        return None


# ---------------------------------------------------------------------------
# Canonical feature order (must match ml_optimizer.py extract_features())
# ---------------------------------------------------------------------------

def _canonical_feature_order() -> list[str]:
    """
    Return the canonical 8 feature names in the order expected by DQN.

    Matches the order in ml_optimizer.CompilerEnv.extract_features():
      BasicBlocksCount, InstructionsCount, BranchCount, MemInstCount,
      MathInstCount, FloatInstCount, VectorInstCount, CallInstCount
    """
    return [
        "BasicBlocksCount",
        "InstructionsCount",
        "BranchCount",
        "MemInstCount",
        "MathInstCount",
        "FloatInstCount",
        "VectorInstCount",
        "CallInstCount",
    ]
