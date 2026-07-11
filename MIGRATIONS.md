# Migration Matrix — V11

| Component | V11 version |
|---|---:|
| Application | 1.1.0 |
| Database schema | 9 |
| Workflow schema | 6 |
| Config schema | 5 |

V11 does not require a database migration. It changes runtime synchronization, generated Agent command files, UI rendering, and test ownership rules. Reinstall `/wf` and `/wstep` command templates after upgrading because generated files now contain absolute launcher and Python paths.
