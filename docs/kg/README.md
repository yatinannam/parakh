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
  caller_line["Caller line"]
  ci["GitHub Actions"]
  cli["CLI"]
  degrader["Degrader"]
  end_state_adapter["EndStateAdapter"]
  heavy_lock["Heavy-model lock"]
  judge["LLM judge"]
  mock_hms["Mock HMS"]
  normalizer["Script-tolerant normaliser"]
  parler_bench["Parler benchmark"]
  quota["Quota guard"]
  recordings["Real recordings + gate"]
  report["Report"]
  report_compare["Comparison page"]
  scenario["Scenario loader"]
  scenario_pack["Hinglish scenario pack"]
  scenario_pack_kn_ta["Kannada and Tamil packs"]
  score_bargein["Barge-in scorer"]
  score_latency["Latency scorer"]
  score_task["Task success"]
  score_wer["WER scorer"]
  t_calibrate_eval["Calibrate free-model wrapper"]
  t_check_keys["Key check"]
  t_kg_render["KG renderer"]
  t_no_emoji["No-emoji guard"]
  test_agent["Clinic test agent"]
  transport_codec["Transport + codec"]
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
  x_pipecat_evals{{"pipecat.evals"}}
  x_whisper{{"faster-whisper small int8"}}
  x_wsl{{"WSL2 Ubuntu"}}
  budget -->|constrained_by| x_groq
  call_driver -->|depends_on| caller_line
  call_driver -->|produces| judge
  call_driver -->|produces| score_bargein
  call_driver -->|produces| score_latency
  call_driver -->|produces| score_wer
  call_driver -->|calls| test_agent
  call_driver -->|calls| transport_codec
  caller_line -->|calls| degrader
  caller_line -->|depends_on| tts_cache
  ci -->|calls| cli
  ci -->|calls| t_kg_render
  ci -->|calls| t_no_emoji
  cli -->|calls| budget
  cli -->|calls| call_driver
  cli -->|calls| heavy_lock
  cli -->|calls| recordings
  cli -->|calls| report_compare
  degrader -->|produces| call_driver
  end_state_adapter -->|calls| mock_hms
  judge -->|depends_on| quota
  judge -->|produces| report
  judge -->|calls| x_gemini
  judge -->|calls| x_groq
  normalizer -->|depends_on| x_indic_translit
  parler_bench -->|depends_on| heavy_lock
  parler_bench -->|calls| x_groq
  parler_bench -->|calls| x_parler
  quota -->|depends_on| budget
  quota -->|constrained_by| x_groq
  recordings -->|produces| call_driver
  report -->|produces| report_compare
  report -->|depends_on| x_whisper
  scenario -->|produces| tts_cache
  scenario_pack -->|depends_on| scenario
  scenario_pack_kn_ta -->|depends_on| scenario
  score_bargein -->|produces| report
  score_latency -->|produces| report
  score_task -->|depends_on| end_state_adapter
  score_task -->|produces| report
  score_wer -->|depends_on| normalizer
  score_wer -->|produces| report
  t_calibrate_eval -->|calls| x_calibrate
  t_calibrate_eval -->|calls| x_openrouter
  t_check_keys -->|calls| x_groq
  test_agent -->|depends_on| heavy_lock
  test_agent -->|calls| mock_hms
  test_agent -->|compatible_with| x_calibrate
  test_agent -->|depends_on| x_edge_tts
  test_agent -->|calls| x_groq
  test_agent -->|depends_on| x_pipecat
  test_agent -->|depends_on| x_whisper
  transport_codec -->|compatible_with| test_agent
  transport_codec -->|depends_on| x_pipecat
  tts_cache -->|produces| degrader
  tts_cache -->|depends_on| x_edge_tts
  tts_cache -->|depends_on| x_parler
  x_calibrate -->|depends_on| x_wsl
  x_pipecat_evals -->|depends_on| x_pipecat
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
  d14[/"D14 Own call driver; pipecat.evals complementary"/]
  d15[/"D15 M3 split into M3a and M3b"/]
  d16[/"D16 Judge models"/]
  d17[/"D17 Judge on by default"/]
  d18[/"D18 One agent process per language"/]
  d19[/"D19 Own Tamil romaniser"/]
  d2[/"D2 Calibrate text sim in WSL"/]
  d20[/"D20 Real runs skip the judge"/]
  d21[/"D21 Parler adoption thresholds"/]
  d3[/"D3 HMS = hospital mgmt system"/]
  d4[/"D4 Scripted caller"/]
  d5[/"D5 Test agent stack"/]
  d6[/"D6 Judge Groq then Gemini"/]
  d8[/"D8 KG as YAML + Mermaid"/]
  d9[/"D9 Pack ships text, not edge-tts audio"/]
  degrader["Degrader"]
  doc_calibrate[("Calibrate analysis")]
  doc_contributing[("CONTRIBUTING")]
  doc_pipecat_evals[("pipecat.evals note")]
  doc_spec[("Design spec")]
  heavy_lock["Heavy-model lock"]
  judge["LLM judge"]
  m3(("M3 Indic layer + judge"))
  mock_hms["Mock HMS"]
  normalizer["Script-tolerant normaliser"]
  parler_bench["Parler benchmark"]
  quota["Quota guard"]
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
  recordings["Real recordings + gate"]
  report["Report"]
  scenario["Scenario loader"]
  scenario_pack["Hinglish scenario pack"]
  scenario_pack_kn_ta["Kannada and Tamil packs"]
  score_bargein["Barge-in scorer"]
  score_wer["WER scorer"]
  t_calibrate_eval["Calibrate free-model wrapper"]
  t_check_keys["Key check"]
  t_kg_render["KG renderer"]
  test_agent["Clinic test agent"]
  transport_codec["Transport + codec"]
  tts_cache["Caller TTS + cache"]
  x_calibrate{{"Calibrate"}}
  x_parler{{"Indic Parler-TTS"}}
  x_pipecat_evals{{"pipecat.evals"}}
  x_whisper{{"faster-whisper small int8"}}
  x_wsl{{"WSL2 Ubuntu"}}
  budget -->|constrained_by| c_free
  budget -->|constrained_by| c_synthetic
  budget -->|decided_by| d10
  budget -->|mitigates| r_quota
  c_mit -->|documented_in| doc_contributing
  call_driver -->|constrained_by| c_windows
  call_driver -->|decided_by| d1
  call_driver -->|decided_by| d14
  call_driver -->|mitigates| r_timing
  ci -->|constrained_by| c_secrets
  ci -->|decided_by| d12
  ci -->|mitigates| r_supply_chain
  d1 -->|documented_in| doc_spec
  d10 -->|mitigates| r_privacy
  d14 -->|documented_in| doc_pipecat_evals
  d14 -->|documented_in| doc_spec
  d15 -->|documented_in| doc_spec
  d16 -->|documented_in| doc_spec
  d17 -->|documented_in| doc_spec
  d18 -->|documented_in| doc_spec
  d19 -->|documented_in| doc_spec
  d20 -->|documented_in| doc_spec
  d21 -->|documented_in| doc_spec
  d9 -->|mitigates| r_license
  degrader -->|mitigates| r_license
  heavy_lock -->|constrained_by| c_cpu
  judge -->|constrained_by| c_synthetic
  judge -->|decided_by| d16
  judge -->|decided_by| d17
  judge -->|decided_by| d20
  judge -->|decided_by| d6
  judge -->|mitigates| r_injection
  m3 -->|decided_by| d15
  mock_hms -->|decided_by| d3
  normalizer -->|decided_by| d19
  normalizer -->|mitigates| r_script
  parler_bench -->|constrained_by| c_free
  parler_bench -->|constrained_by| c_synthetic
  parler_bench -->|decided_by| d21
  quota -->|constrained_by| c_free
  quota -->|mitigates| r_quota
  r_license -->|documented_in| doc_contributing
  r_llm_behaviour -->|documented_in| doc_calibrate
  recordings -->|constrained_by| c_synthetic
  recordings -->|decided_by| d10
  recordings -->|decided_by| d20
  recordings -->|mitigates| r_privacy
  report -->|mitigates| r_llm_behaviour
  scenario -->|decided_by| d4
  scenario_pack -->|decided_by| d9
  scenario_pack_kn_ta -->|decided_by| d18
  scenario_pack_kn_ta -->|decided_by| d9
  score_bargein -->|mitigates| r_timing
  score_wer -->|decided_by| d11
  score_wer -->|mitigates| r_alignment
  t_calibrate_eval -->|constrained_by| c_free
  t_calibrate_eval -->|constrained_by| c_synthetic
  t_calibrate_eval -->|decided_by| d2
  t_check_keys -->|constrained_by| c_secrets
  t_kg_render -->|decided_by| d8
  test_agent -->|decided_by| d18
  test_agent -->|decided_by| d5
  test_agent -->|mitigates| r_llm_behaviour
  transport_codec -->|mitigates| r_alignment
  transport_codec -->|mitigates| r_privacy
  tts_cache -->|decided_by| d9
  x_calibrate -->|constrained_by| c_mit
  x_calibrate -->|decided_by| d2
  x_parler -->|constrained_by| c_cpu
  x_pipecat_evals -->|decided_by| d14
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
    normalizer["Script-tolerant normaliser"]
    report["Report"]
    scenario["Scenario loader"]
    score_latency["Latency scorer"]
    score_wer["WER scorer"]
    test_agent["Clinic test agent"]
    transport_codec["Transport + codec"]
    tts_cache["Caller TTS + cache"]
  end
  subgraph g_m2[" "]
    m2(("M2 Degradation + interruptions"))
    caller_line["Caller line"]
    degrader["Degrader"]
    report_compare["Comparison page"]
    score_bargein["Barge-in scorer"]
  end
  subgraph g_m3[" "]
    m3(("M3 Indic layer + judge"))
    heavy_lock["Heavy-model lock"]
    judge["LLM judge"]
    parler_bench["Parler benchmark"]
    quota["Quota guard"]
    recordings["Real recordings + gate"]
    scenario_pack["Hinglish scenario pack"]
    scenario_pack_kn_ta["Kannada and Tamil packs"]
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
