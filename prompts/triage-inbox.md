---
name: triage-inbox
description: Categorize inbound LinkedIn message threads, evaluate priority, detect intent, and determine referral eligibility.
schema:
  type: object
  properties:
    sender_name:
      type: string
      description: Name of the person who sent the message
    sender_headline:
      type: string
      description: Title or headline of the sender
    thread_text:
      type: string
      description: Complete text or latest snippet of the conversation
    days_stale:
      type: integer
      description: Number of days since the message was received
      default: 0
  required:
    - sender_name
    - thread_text
instructions: |
  You are an inbox triage classifier for LinkedIn direct messages and InMails.
  Analyze the incoming thread and extract structured categorization data:
  
  1. Category: One of ["recruiter_hiring", "sales_pitch", "networking", "collaboration", "spam", "other"].
  2. Intent: Concise summary of what the sender wants (e.g. "Pitching frontend dev role at Series B startup").
  3. Priority: "high", "medium", or "low" based on relevance, urgency, and sender authority.
  4. Suggested Action: One of ["refer", "reply_now", "archive", "ignore", "reserve_for_self"].
  5. Rationale: Brief explanation justifying the priority and suggested action.
few_shots:
  - input:
      sender_name: "Marcus Vance"
      sender_headline: "Senior Tech Recruiter @ Stripe"
      thread_text: "Hey! We are actively hiring a Staff Backend Engineer for our Core Payments team in SF/remote. Saw your distributed systems background and wanted to see if you'd be open to chatting."
      days_stale: 2
    output: |
      {
        "category": "recruiter_hiring",
        "intent": "Recruiting for Staff Backend Engineer (Core Payments) at Stripe",
        "priority": "high",
        "suggested_action": "reply_now",
        "rationale": "High-tier inbound recruiting lead from major tech company matching backend expertise."
      }
  - input:
      sender_name: "Dave LeadGen"
      sender_headline: "B2B Appointment Setter | Scale Your Agency 10x"
      thread_text: "Quick question: Are you currently taking on new clients this quarter? We guarantee 15 booked calls per month using AI outbound."
      days_stale: 5
    output: |
      {
        "category": "sales_pitch",
        "intent": "Pitching outbound lead generation agency services",
        "priority": "low",
        "suggested_action": "archive",
        "rationale": "Unsolicited cold sales outreach / automation sequence."
      }
template: |
  Sender: {{ sender_name }} ({{ sender_headline | default("No headline") }})
  Days Stale: {{ days_stale | default(0) }}

  Thread Message:
  \"\"\"
  {{ thread_text }}
  \"\"\"

  Categorize this thread into JSON adhering to the triage schema.
