"""Step 3: run the check. One run JSON is one run: once its cases have verdicts it is complete and stays so.
Changes to the answer key afterwards are shown, and checking them is a separate, optional step."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from eval import judge, providers
from eval import reality_check as rc

from .state import S


def _run(check: dict, recheck: bool = False):
    bar = st.progress(0.0, text="Starting")
    live = st.empty()
    try:
        out = rc.run_check(check, S.cases, snapshot=S.snapshot, recheck=recheck,
                           progress=lambda step, i, n: bar.progress(i / n if n else 0.0, text=f"{step}: {i} of {n}"),
                           notify=lambda text: live.caption(text))
    except judge.JudgeUnavailable as e:
        st.error(f"The check could not run: {e}")
        return
    st.session_state["rc_last_run"] = {"switches": out.get("switches", []), "models": out.get("models", []),
                                       "by_rule": out.get("by_rule", 0)}
    if out["stopped"]:
        st.warning(f"Stopped with {out['left']} verdicts left: {out['stopped']} Everything done so far is saved. "
                   f"Press the button again later to carry on.")
    else:
        st.rerun()


def _step3(check: dict):
    scope = rc.scope(check)
    n_cases = len(scope) if scope is not None else sum(c["data_room"] == check["data_room"] for c in S.cases)
    left = rc.remaining(check, S.cases)
    done = len(check["case_verdicts"]) + len(check["new_verdicts"])
    with st.container(border=True):
        st.markdown("##### Step 3 · Run the check")
        if not n_cases:
            st.info(f"{check['data_room']} has no ground-truth case in this answer key yet. The check will only test each "
                    f"finding against the documents. Add cases through the evaluation sheet to measure what was found and missed.")
        if not left["total"]:
            st.success(f"This run is complete: {done} verdicts on {n_cases} ground-truth cases. It stays as it is; "
                       f"changing the answer key does not reopen it.")
        else:
            st.write(f"{done} verdicts done, up to {left['total']} to go: one model call per ground-truth case "
                     f"({n_cases}), then one per finding that maps to no case.")
            if not judge.credentials_present():
                st.error(f"No model is set up, so the check cannot run. {judge.judge_label()}")
            elif st.button(f"Run the check ({left['total']} verdicts)", type="primary"):
                _run(check)
            cfg = providers.settings()
            chain = cfg.get("chain") or []
            st.caption(f"Model: {chain[0]['model'] if chain else judge.judge_label()}"
                       + (f", with {len(chain) - 1} more in reserve: when one is busy or used up, the next carries on." if len(chain) > 1 else ".")
                       + " Every verdict is saved as it arrives, so nothing is lost if it stops.")
        if not left["total"] and done:
            _answer_key_changed(check, left)
        _last_run()


def _answer_key_changed(check: dict, left: dict):
    new, stale = rc.added_since(check, S.cases), left["stale"]
    if not (new or stale):
        return
    with st.expander(f"The answer key changed after this run ({len(new)} new, {len(stale)} edited cases)"):
        st.write("These are not part of this run's result, and the verdicts it has stand. Check them only if you want "
                 "this run measured against the newer answer key too.")
        if new:
            st.caption(f"Added since: {', '.join(new)}")
        if stale:
            st.caption(f"Edited since their verdict: {', '.join(stale)}")
        if judge.credentials_present() and st.button(f"Check these as well ({len(new) + len(stale)} cases)"):
            _run(check, recheck=True)


def _last_run():
    last = st.session_state.get("rc_last_run")
    if not (last and (last["switches"] or last["by_rule"])):
        return
    with st.expander("Last run: models and switches"):
        if last["by_rule"]:
            st.write(f"{last['by_rule']} cases had no related finding and were decided by rule, with no model call.")
        if last["models"]:
            st.dataframe(pd.DataFrame(last["models"]), hide_index=True, width="stretch")
        for e in last["switches"]:
            st.caption(e)
        if st.button("Try every model again from the top", help="Models that were busy or used up rest for a while. "
                     "This forgets those rests, for example after a quota resets."):
            providers.reset_clients()
            st.session_state.pop("rc_last_run", None)
            st.rerun()
