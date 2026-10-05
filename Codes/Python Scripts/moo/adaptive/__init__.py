"""
moo/adaptive/__init__.py — Week 11: Adaptive Self-Learning package.

This package adds a durable experience-learning layer on top of the
existing optimization-selection pipeline.

Architecture
------------
The existing pipeline (DQN → MOO → selection → benchmark → Week 10
regression) is UNCHANGED.  Week 11 adds a thin learning layer:

  selected strategy + benchmark outcome + regression outcome
       ↓
  ExperienceRecord (schema.py)
       ↓
  Validated & stored in ExperienceStore (storage.py)
       ↓
  ReplayBuffer samples experiences for the Learner (storage.py)
       ↓
  DQNLearner updates a candidate model (learner.py)
       ↓
  CandidateModel artifact — NOT automatically promoted to production

Public surface
--------------
  from moo.adaptive.schema   import ExperienceRecord, ModelVersionInfo, ADAPTIVE_SCHEMA_VERSION
  from moo.adaptive.reward   import compute_reward, RewardConfig, is_performance_inconclusive
  from moo.adaptive.validator import validate_experience
  from moo.adaptive.storage  import ExperienceStore, ReplayBuffer
  from moo.adaptive.learner  import DQNLearner
  from moo.adaptive.adapter  import experience_from_program_comparison

Design rules enforced here
--------------------------
* The production model (ml_optimizer_model.pth) is NEVER overwritten
  by this package.  Candidate models land in adaptive/candidate_models/.
* All public functions are deterministic when seeds are supplied.
* No GUI files are imported or touched.
* No second benchmark system is created.
"""

from .schema import ExperienceRecord, ModelVersionInfo, ADAPTIVE_SCHEMA_VERSION
from .reward import compute_reward, RewardConfig, is_performance_inconclusive
from .validator import validate_experience
from .storage import ExperienceStore, ReplayBuffer
from .learner import DQNLearner
from .adapter import experience_from_program_comparison

__version__ = "0.1.0"
__week__ = 11
