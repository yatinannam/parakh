# Parakh knowledge graph

Source of truth: [`graph.yaml`](graph.yaml). The diagrams below are generated from it by `python -m tools.kg_render`; do not edit them by hand. CI and pre-commit run `python -m tools.kg_render --check` and fail when they are out of date.

Node types and shapes:

| Type | Meaning | Shape |
|---|---|---|
| component | Code in this repo | rectangle |
| external | Third-party service, library or tool | hexagon |
| constraint | Hard rule from CLAUDE.md or the spec | stadium |
| decision | Recorded design decision (D-numbers in the spec) | parallelogram |
| risk | Edge-case group (EC-numbers in the spec) | flag |
| doc | Document in `docs/` | cylinder |
| milestone | Build milestone | circle |

## Pipeline and dependencies

Components and externals, with the edges between them.

<!-- kg:begin pipeline -->
```mermaid
flowchart LR
  budget["Budget + quota guard"]
  call_driver["Call driver"]
  ci["GitHub Actions"]
  cli["CLI"]
  degrader["Degrader"]
  end_state_adapter["EndStateAdapter"]
  judge["LLM judge"]
  mock_hms["Mock HMS"]
  normalizer["Script-tolerant normaliser"]
  report["Report"]
  scenario["Scenario loader"]
  score_latency["Latency scorer"]
  score_task["Task success"]
  score_wer["WER scorer"]
  t_calibrate_eval["Calibrate free-model wrapper"]
  t_check_keys["Key check"]
  t_kg_render["KG renderer"]
  t_no_emoji["No-emoji guard"]
  test_agent["Clinic test agent"]
  tts_cache["Caller TTS + cache"]
  x_100ms{{"100ms"}}
  x_calibrate{{"Calibrate"}}
  x_edge_tts{{"edge-tts"}}
  x_gemini{{"Gemini API"}}
  x_groq{{"Groq"}}
  x_indic_translit{{"indic-transliteration"}}
  x_openrouter{{"OpenRouter :free"}}
  x_parler{{"Indic Parler-TTS"}}
  x_pipecat{{"Pipecat"}}
  x_whisper{{"faster-whisper small int8"}}
  x_wsl{{"WSL2 Ubuntu"}}
  budget -->|constrained_by| x_groq
  call_driver -->|produces| judge
  call_driver -->|produces| score_latency
  call_driver -->|produces| score_wer
  call_driver -->|calls| test_agent
  call_driver -->|depends_on| x_pipecat
  ci -->|calls| cli
  ci -->|calls| t_kg_render
  ci -->|calls| t_no_emoji
  cli -->|calls| budget
  cli -->|calls| call_driver
  degrader -->|produces| call_driver
  end_state_adapter -->|calls| mock_hms
  judge -->|produces| report
  judge -->|calls| x_gemini
  judge -->|calls| x_groq
  normalizer -->|depends_on| x_indic_translit
  report -->|depends_on| x_whisper
  scenario -->|produces| tts_cache
  score_latency -->|produces| report
  score_task -->|depends_on| end_state_adapter
  score_task -->|produces| report
  score_wer -->|depends_on| normalizer
  score_wer -->|produces| report
  t_calibrate_eval -->|calls| x_calibrate
  t_calibrate_eval -->|calls| x_openrouter
  t_check_keys -->|calls| x_groq
  test_agent -->|calls| mock_hms
  test_agent -->|compatible_with| x_calibrate
  test_agent -->|depends_on| x_edge_tts
  test_agent -->|calls| x_groq
  test_agent -->|depends_on| x_pipecat
  tts_cache -->|produces| degrader
  tts_cache -->|depends_on| x_edge_tts
  tts_cache -->|depends_on| x_parler
  x_calibrate -->|depends_on| x_wsl
```
<!-- kg:end pipeline -->

## Constraints, decisions and risks

Every edge that touches a constraint, decision or risk.

<!-- kg:begin governance -->
```mermaid
flowchart TB
  budget["Budget + quota guard"]
  c_cpu(["CPU only, 16 GB"])
  c_free(["Free only, no card"])
  c_mit(["MIT, no Calibrate code"])
  c_secrets(["No secrets in git"])
  c_synthetic(["Synthetic data to free LLM APIs"])
  c_windows(["Windows dev box"])
  call_driver["Call driver"]
  ci["GitHub Actions"]
  d1[/"D1 Standalone, Pipecat-compatible"/]
  d10[/"D10 Real recordings stay local"/]
  d11[/"D11 Headline = conversation loose WER"/]
  d12[/"D12 Audience: portfolio first"/]
  d2[/"D2 Calibrate text sim in WSL"/]
  d3[/"D3 HMS = hospital mgmt system"/]
  d4[/"D4 Scripted caller"/]
  d5[/"D5 Test agent stack"/]
  d6[/"D6 Judge Groq then Gemini"/]
  d8[/"D8 KG as YAML + Mermaid"/]
  d9[/"D9 Pack ships text, not edge-tts audio"/]
  doc_calibrate[("Calibrate analysis")]
  doc_spec[("Design spec")]
  judge["LLM judge"]
  mock_hms["Mock HMS"]
  normalizer["Script-tolerant normaliser"]
  r_alignment>"Turn alignment"]
  r_injection>"Judge prompt injection"]
  r_license>"Licence contamination"]
  r_llm_behaviour>"Hosted LLM behaviour"]
  r_privacy>"Real data leakage"]
  r_quota>"Free-tier quota"]
  r_script>"Script/spelling mismatch"]
  r_supply_chain>"Supply chain (CI and hooks)"]
  r_timing>"Timing accuracy"]
  r_windows_install>"Windows install gaps"]
  report["Report"]
  scenario["Scenario loader"]
  score_wer["WER scorer"]
  t_calibrate_eval["Calibrate free-model wrapper"]
  t_check_keys["Key check"]
  t_kg_render["KG renderer"]
  test_agent["Clinic test agent"]
  tts_cache["Caller TTS + cache"]
  x_calibrate{{"Calibrate"}}
  x_parler{{"Indic Parler-TTS"}}
  x_whisper{{"faster-whisper small int8"}}
  x_wsl{{"WSL2 Ubuntu"}}
  budget -->|constrained_by| c_free
  budget -->|constrained_by| c_synthetic
  budget -->|decided_by| d10
  budget -->|mitigates| r_quota
  call_driver -->|constrained_by| c_windows
  call_driver -->|decided_by| d1
  call_driver -->|mitigates| r_timing
  ci -->|constrained_by| c_secrets
  ci -->|decided_by| d12
  ci -->|mitigates| r_supply_chain
  d1 -->|documented_in| doc_spec
  d10 -->|mitigates| r_privacy
  d9 -->|mitigates| r_license
  judge -->|constrained_by| c_synthetic
  judge -->|decided_by| d6
  judge -->|mitigates| r_injection
  mock_hms -->|decided_by| d3
  normalizer -->|mitigates| r_script
  r_llm_behaviour -->|documented_in| doc_calibrate
  report -->|mitigates| r_llm_behaviour
  scenario -->|decided_by| d4
  score_wer -->|decided_by| d11
  score_wer -->|mitigates| r_alignment
  t_calibrate_eval -->|constrained_by| c_free
  t_calibrate_eval -->|constrained_by| c_synthetic
  t_calibrate_eval -->|decided_by| d2
  t_check_keys -->|constrained_by| c_secrets
  t_kg_render -->|decided_by| d8
  test_agent -->|decided_by| d5
  test_agent -->|mitigates| r_llm_behaviour
  tts_cache -->|decided_by| d9
  x_calibrate -->|constrained_by| c_mit
  x_calibrate -->|decided_by| d2
  x_parler -->|constrained_by| c_cpu
  x_whisper -->|constrained_by| c_cpu
  x_wsl -->|mitigates| r_windows_install
```
<!-- kg:end governance -->

## Milestones

What each milestone delivers.

<!-- kg:begin milestones -->
```mermaid
flowchart LR
  subgraph g_backlog[" "]
    backlog(("Backlog (after M5)"))
    x_100ms{{"100ms"}}
  end
  subgraph g_m0[" "]
    m0(("M0 Foundations + Task 1 run"))
    ci["GitHub Actions"]
    t_calibrate_eval["Calibrate free-model wrapper"]
    t_check_keys["Key check"]
    t_kg_render["KG renderer"]
    t_no_emoji["No-emoji guard"]
    x_calibrate{{"Calibrate"}}
  end
  subgraph g_m1[" "]
    m1(("M1 MVP clean, latency + WER"))
    budget["Budget + quota guard"]
    call_driver["Call driver"]
    cli["CLI"]
    report["Report"]
    scenario["Scenario loader"]
    score_latency["Latency scorer"]
    score_wer["WER scorer"]
    test_agent["Clinic test agent"]
    tts_cache["Caller TTS + cache"]
  end
  subgraph g_m2[" "]
    m2(("M2 Degradation + interruptions"))
    degrader["Degrader"]
  end
  subgraph g_m3[" "]
    m3(("M3 Indic layer + judge"))
    judge["LLM judge"]
    normalizer["Script-tolerant normaliser"]
  end
  subgraph g_m4[" "]
    m4(("M4 HMS adapter + CI e2e"))
    end_state_adapter["EndStateAdapter"]
    mock_hms["Mock HMS"]
    score_task["Task success"]
  end
  subgraph g_m5[" "]
    m5(("M5 Public release"))
  end
  backlog -->|depends_on| m5
  m1 -->|depends_on| m0
  m2 -->|depends_on| m1
  m3 -->|depends_on| m2
  m4 -->|depends_on| m3
  m5 -->|depends_on| m4
```
<!-- kg:end milestones -->

## How to update

1. Add or change nodes and edges in `graph.yaml`. Every new component, decision or risk gets a node.
2. Run `uv run python -m tools.kg_render`.
3. Commit `graph.yaml` and `README.md` together.
