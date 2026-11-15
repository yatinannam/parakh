# Parakh knowledge graph

Source of truth: [`graph.yaml`](graph.yaml). These diagrams are views of it. Until the render script lands (M0), keep them in sync by hand.

Node types: constraint, component, external, decision, risk, doc, milestone.

## Pipeline and dependencies

```mermaid
flowchart LR
  scenario[Scenario loader] --> tts_cache[Caller TTS + cache]
  tts_cache --> degrader[Degrader]
  degrader --> call_driver[Call driver]
  call_driver -- "Pipecat protobuf WS" --> test_agent[Clinic test agent]
  test_agent -- tools --> mock_hms[(Mock HMS)]
  call_driver --> score_latency[Latency scorer]
  call_driver --> score_wer[WER scorer]
  score_wer --> normalizer[Script-tolerant normaliser]
  score_task[Task success] --> end_state_adapter[EndStateAdapter] --> mock_hms
  call_driver --> judge[LLM judge]
  score_latency --> report[Report JSON + HTML]
  score_wer --> report
  score_task --> report
  judge --> report
  cli[CLI] --> call_driver
  cli --> budget[Budget + quota guard]
  ci[GitHub Actions] --> cli

  tts_cache -.-> x_edge_tts{{edge-tts}}
  tts_cache -.-> x_parler{{Indic Parler-TTS}}
  test_agent -.-> x_groq{{Groq}}
  judge -.-> x_groq
  judge -.-> x_gemini{{Gemini}}
  normalizer -.-> x_translit{{indic-transliteration}}
  report -.-> x_whisper{{faster-whisper}}
  call_driver -.-> x_pipecat{{Pipecat}}
  test_agent -. compatible .-> x_calibrate{{Calibrate}}
```

## Constraints, decisions and risks

```mermaid
flowchart TB
  subgraph Constraints
    c_free[Free only, no card]
    c_cpu[CPU only, 16 GB]
    c_synthetic[Synthetic data to free LLM APIs]
    c_secrets[No secrets in git]
    c_mit[MIT, no Calibrate code]
    c_windows[Windows dev box]
  end
  subgraph Decisions
    d1[D1 Standalone, Pipecat-compatible]
    d2[D2 Calibrate text sim in WSL]
    d3[D3 HMS = hospital mgmt system]
    d4[D4 Scripted caller]
    d9[D9 Pack ships text only]
    d10[D10 Real recordings stay local]
    d11[D11 Conversation loose WER]
  end
  subgraph Risks
    r_timing[Timing accuracy]
    r_quota[Free-tier quota]
    r_script[Script/spelling mismatch]
    r_license[Licence contamination]
    r_privacy[Real data leakage]
  end
  c_mit --> d1
  c_free --> d2
  c_synthetic --> d10
  c_windows --> r_timing
  c_free --> r_quota
  d9 -- mitigates --> r_license
  d10 -- mitigates --> r_privacy
  d11 -- mitigates --> r_script
```

## Milestones

```mermaid
flowchart LR
  m0[M0 Foundations + Task 1] --> m1[M1 MVP] --> m2[M2 Degradation] --> m3[M3 Indic + judge] --> m4[M4 HMS + CI] --> m5[M5 Release]
```

## How to update

1. Add or change nodes and edges in `graph.yaml`. Give every new component, decision or risk a node.
2. Update the diagrams above (later: `python scripts/kg_render.py`).
3. Commit both files together.
