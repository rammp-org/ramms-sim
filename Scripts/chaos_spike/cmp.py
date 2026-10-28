import json, sys, numpy as np
C=json.load(open(sys.argv[1])); M=json.load(open(sys.argv[2] if len(sys.argv) > 2 else 'mj_ref.json'))
mt=np.array([r['t'] for r in M])
joints=[k for k in M[0]['q']]
print("%-28s %8s %8s %8s %8s" % ("joint", "rms", "max", "ss@6s_c", "ss@6s_mj"))
for j in joints:
    ct=np.array([r['t'] for r in C]); cq=np.array([r['q'][j] for r in C]); mq=np.interp(ct, mt, [r['q'][j] for r in M])
    e=cq-mq; i6=np.argmin(abs(ct-6.0))
    print("%-28s %8.4f %8.4f %8.4f %8.4f" % (j, np.sqrt(np.mean(e**2)), np.max(abs(e)), cq[i6], mq[i6]))
print("loop gap max cm: chaos %.4f  mj %.4f" % (max(r['loop_gap_cm'] for r in C), max(r['loop_gap_cm'] for r in M)))
