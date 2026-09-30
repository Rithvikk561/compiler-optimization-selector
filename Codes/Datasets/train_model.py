import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import xgboost as xgb
import sklearn
import joblib
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import StratifiedKFold, cross_val_score, GridSearchCV, cross_val_predict
from xgboost import XGBClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

print(f"XGBoost: {xgb.__version__}")
print(f"scikit-learn: {sklearn.__version__}")

# Phase 2 — Data Loading and Preprocessing
df = pd.read_csv(r"Codes\Datasets\dataset.csv")
print("Dataset shape:", df.shape)
print("Class distribution:\n", df["OptimizationLevel"].value_counts())
print("Missing values:\n", df.isnull().sum())

# Print pre-optimization feature averages vs labels as requested
print("\nMean Feature Values Across Optimization Levels:")
feature_cols = [c for c in df.columns if c not in ["OptimizationLevel", "Program", "SecurityChecks", "ExecTimeSeconds"]]
print(df.groupby("OptimizationLevel")[feature_cols].mean().round(2))

# Add derived features (Option 2 fix)
eps = 1e-6
df["mem_ratio"]      = df["MemInstCount"] / (df["InstructionsCount"] + eps)
df["branch_density"] = df["BranchCount"] / (df["BasicBlocksCount"] + eps)
df["avg_block_size"] = df["InstructionsCount"] / (df["BasicBlocksCount"] + eps)
df["code_size_delta"]= df["CodeSizeBytes"] / (df["InstructionsCount"] + eps)

# Option C: Merge similar levels — 3-class (None / Moderate / Aggressive) (Option 1 fix)
df["label"] = df["OptimizationLevel"].map({"-O0":"none", "-O1":"moderate", "-O2":"aggressive", "-O3":"aggressive"})

# Encode the target
le = LabelEncoder()
ignore_cols = ["OptimizationLevel", "label"] + ([col for col in ["Program", "SecurityChecks", "ExecTimeSeconds"] if col in df.columns])
X = df.drop(ignore_cols, axis=1)
X = X.fillna(0)
y = le.fit_transform(df["label"])

print("\nClass mapping:", dict(zip(le.classes_, le.transform(le.classes_))))

# Apply SMOTE to synthetically balance the 3 classes (Option 3 fix)
from imblearn.over_sampling import SMOTE
X_res, y_res = SMOTE(random_state=42).fit_resample(X, y)
print(f"After SMOTE, shape of X is: {X_res.shape}")

# Reassign X and y to the SMOTE resampled variants
X, y = X_res, y_res

# Phase 3 — Baseline cross-validation
model = XGBClassifier(
    n_estimators=100,
    max_depth=4,
    learning_rate=0.1,
    subsample=0.8,
    colsample_bytree=0.8,
    eval_metric="mlogloss",
    random_state=42
)

cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
scores = cross_val_score(model, X, y, cv=cv, scoring="accuracy")

print(f"\nBaseline CV Accuracy: {scores.mean():.3f} ± {scores.std():.3f}")
print(f"Individual folds: {scores}")

# Phase 4 — Hyperparameter Tuning
param_grid = {
    "n_estimators":    [50, 100, 200],
    "max_depth":       [3, 4, 5],
    "learning_rate":   [0.05, 0.1, 0.2],
    "subsample":       [0.7, 0.8, 1.0],
    "colsample_bytree":[0.7, 0.8, 1.0],
}

grid_search = GridSearchCV(
    estimator=XGBClassifier(
        eval_metric="mlogloss",
        random_state=42
    ),
    param_grid=param_grid,
    cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=42),
    scoring="accuracy",
    n_jobs=-1,
    verbose=1
)

print("\nStarting Hyperparameter Tuning...")
grid_search.fit(X, y)
print("Best parameters:", grid_search.best_params_)
print(f"Best CV accuracy: {grid_search.best_score_:.3f}")

best_model = grid_search.best_estimator_

# Phase 5 — Evaluation and Metrics
y_pred = cross_val_predict(best_model, X, y, cv=cv)

report = classification_report(y, y_pred, target_names=le.classes_)
print("\nClassification Report:\n", report)

cm = confusion_matrix(y, y_pred)
plt.figure(figsize=(6, 5))
sns.heatmap(cm, annot=True, fmt="d", xticklabels=le.classes_, yticklabels=le.classes_, cmap="Blues")
plt.xlabel("Predicted")
plt.ylabel("Actual")
plt.title("Confusion Matrix — XGBoost (5-Fold CV)")
plt.tight_layout()
plt.savefig("confusion_matrix.png", dpi=150)
print("Saved confusion_matrix.png")

# Phase 6 — Feature Importance Analysis
best_model.fit(X, y)

importances = best_model.feature_importances_
feature_names = X.columns
sorted_idx = np.argsort(importances)[::-1]

plt.figure(figsize=(10, 6))
plt.bar(range(len(importances)), importances[sorted_idx], color="steelblue")
plt.xticks(range(len(importances)), feature_names[sorted_idx], rotation=45, ha="right")
plt.title("Feature Importance — XGBoost")
plt.xlabel("IR Feature")
plt.ylabel("Importance Score")
plt.tight_layout()
plt.savefig("feature_importance.png", dpi=150)
print("Saved feature_importance.png")

# Phase 7 — Baseline Comparison
models = {
    "XGBoost (tuned)":  best_model,
    "Random Forest":     RandomForestClassifier(n_estimators=100, random_state=42),
    "Logistic Regression": Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=500, C=1.0, random_state=42))
    ])
}

comparison_output = []
comparison_output.append(f"{'Model':<25} {'CV Accuracy':>12} {'Std Dev':>10}")
comparison_output.append("-" * 50)
print("\n" + comparison_output[0])
print(comparison_output[1])
for name, m in models.items():
    s = cross_val_score(m, X, y, cv=cv, scoring="accuracy")
    comp_str = f"{name:<25} {s.mean():>12.3f} {s.std():>10.3f}"
    comparison_output.append(comp_str)
    print(comp_str)

with open("model_comparison.txt", "w") as f:
    f.write("\n".join(comparison_output))
print("Saved model_comparison.txt")

# Phase 8 — Save Model
joblib.dump(best_model, "xgb_compiler_opt.pkl")
joblib.dump(le,         "label_encoder.pkl")
print("Saved xgb_compiler_opt.pkl and label_encoder.pkl")
