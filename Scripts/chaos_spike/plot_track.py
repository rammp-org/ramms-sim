import json, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sys
C = json.load(open(sys.argv[1])); M = json.load(open(sys.argv[2]))
J = [("joint_1", "joint 1 (base yaw)"), ("joint_2", "joint 2 (shoulder)"), ("joint_4", "joint 4 (elbow)"), ("joint_6", "joint 6 (wrist)")]
plt.rcParams.update({"font.size": 10, "axes.edgecolor": "#b9b8b2", "axes.labelcolor": "#52514e", "xtick.color": "#52514e", "ytick.color": "#52514e"})
fig, axs = plt.subplots(2, 2, figsize=(10, 5.6), sharex=True, facecolor="#fcfcfb")
for ax, (j, title) in zip(axs.ravel(), J):
    ax.set_facecolor("#fcfcfb"); ax.grid(True, color="#e6e5e0", lw=0.8); ax.set_axisbelow(True)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    ax.plot([r["t"] for r in M], [r["target"][j] for r in M], color="#8a8983", lw=1.2, ls=(0, (2, 2)), label="target")
    ax.plot([r["t"] for r in M], [r["q"][j] for r in M], color="#eb6834", lw=2, label="MuJoCo (URLab model)")
    ax.plot([r["t"] for r in C], [r["q"][j] for r in C], color="#2a78d6", lw=2, label="Chaos (built from the same MJCF)")
    ax.set_title(title, loc="left", fontsize=10, color="#0b0b0b")
for ax in axs[1]: ax.set_xlabel("time (s)")
for ax in axs[:, 0]: ax.set_ylabel("angle (rad)")
h, l = axs[0, 0].get_legend_handles_labels()
fig.legend(h, l, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 1.0))
fig.tight_layout(rect=(0, 0, 1, 0.94))
fig.savefig(sys.argv[3], dpi=150, facecolor=fig.get_facecolor())
