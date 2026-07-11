# Upgrade to V11

1. Stop the Controller and back up `data/store.sqlite3` and local configuration.
2. Replace the application files with V11; database/workflow/config schema numbers are unchanged from V10.
3. Reinstall interactive commands because V11 commands pin absolute Python and launcher paths:

   ```bash
   python scripts/install_agent_commands.py --target all --scope project --project <project>
   ```

4. Confirm the installer prints `aiwf.agent-command-verification.v1` with `ok: true`.
5. Run `python scripts/run_production_acceptance.py --quick --output reports/production-acceptance-v11`.
6. On the Windows target, open Qwen/OpenCode, type `/`, and verify `/wf` and `/wstep` are listed.

Rollback: stop the Controller, restore the V10 package and SQLite backup, then reinstall the V10 command templates.
