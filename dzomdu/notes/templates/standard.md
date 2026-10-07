---
name: Standard minutes
description: Summary, decisions, action items and minutes by topic.
instructions: >
  Write in clear, neutral English. Keep the summary to one short paragraph (3-5 sentences).
  Minutes are grouped by topic with concise bullet points; attribute important points to
  the person who made them.
---
## Summary

{{ notes.summary }}

## Decisions

{% for d in notes.decisions %}
- {{ d.decision }} {{ cite(d) }}
{% else %}
- _No decisions recorded._
{% endfor %}

## Action items

{% for a in notes.action_items %}
- [ ] {{ task(a) }}
{% else %}
- _No action items recorded._
{% endfor %}

## Minutes

{% for t in notes.topics %}
### {{ t.title }}

{% for p in t.points %}
- {{ p }}
{% endfor %}
{% if t.source_turns %}
- _Source: {{ cite(t, wrap=False) }}_
{% endif %}

{% endfor %}
{% if notes.open_questions %}
## Open questions

{% for q in notes.open_questions %}
- {{ q }}
{% endfor %}
{% endif %}
{% if notes.next_meeting %}

**Next meeting:** {{ notes.next_meeting }}
{% endif %}
