# ATR Self-Evolution Specification

## Concept
ATR Self-Evolution is a trace-guided optimization subsystem for Autonomous Experimental Research.

It does not train model weights. It evolves textual/configurable/runtime artifacts: prompts, tool descriptions, report templates, LangGraph configs, policies, and optional code patches.

## Formula

J(theta)=E_{tau~D}[w_Q Q(tau,theta)-w_C C(tau,theta)-w_T T(tau,theta)-w_R R(tau,theta)]

Gate(theta)=AND_i g_i(theta)=1

Only candidates satisfying the gate can be activated.

## Candidate Lifecycle
draft -> generated -> evaluated -> gate_passed -> approved -> active_next_run -> active -> retired

Failure states: rejected, regression_failed, safety_failed, rollback_required.
