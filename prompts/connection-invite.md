---
name: connection-invite
description: Generate high-acceptance rate LinkedIn connection invitation notes strictly under 300 characters.
schema:
  type: object
  properties:
    recipient_name:
      type: string
      description: First name of recipient
    shared_context:
      type: string
      description: Shared group, mutual connection, event, company, or post
    reason:
      type: string
      description: Specific focus area or reason to connect
  required:
    - recipient_name
    - shared_context
instructions: |
  LinkedIn connection invitation notes have a strict hard limit of 300 characters.
  
  RULES:
  1. Character Limit: Under NO circumstance exceed 300 characters (including spaces and punctuation). Target 180-260 characters.
  2. Immediate Context: State the shared connection, event, or specific work context in sentence 1.
  3. Clear Reason: Give a genuine reason for wanting to connect (following their work, learning about a shared topic).
  4. Zero Pitching: Do not sell, pitch, or ask for calls. The only goal is acceptance.
few_shots:
  - input:
      recipient_name: "Elena"
      shared_context: "your recent post on building LLM evals in production"
      reason: "deeply interested in automated regression benchmarks"
    output: "Hi Elena, really enjoyed your breakdown on LLM evals in production—especially the points on prompt regression testing. Building in a similar space and would love to stay connected to follow your work!"
  - input:
      recipient_name: "Devon"
      shared_context: "fellow Stanford alumni in distributed systems"
      reason: "following your work at Databricks"
    output: "Hi Devon, saw we're both Stanford alumni working on distributed data infrastructure. Impressed by what Databricks is doing with lakehouse streaming—would love to connect and follow your updates!"
template: |
  Hi {{ recipient_name }}, enjoyed {{ shared_context }}. I'm {{ reason }} and would love to connect here to follow your updates!
