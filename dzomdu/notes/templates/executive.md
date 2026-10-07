---
name: Executive summary
description: Short brief for leadership - outcomes, decisions and owners only.
instructions: >
  Audience is a busy director who did not attend. Be brief and outcome-focused.
  The summary is at most 3 sentences. Topics hold at most 3 points each, only those that
  matter for decisions, risks or deadlines. Skip small talk and procedural discussion.
---
## Brief

{{ notes.summary }}

{% if notes.decisions %}
## Decisions

{% for d in notes.decisions %}
- **{{ d.decision }}** {{ cite(d) }}
{% endfor %}
{% endif %}

## Actions

{% for a in notes.action_items %}
- [ ] {{ task(a) }}
{% else %}
- _None._
{% endfor %}

{% if notes.topics %}
## Key points

{% for t in notes.topics %}
- **{{ t.title }}**: {{ t.points | join("; ") }}
{% endfor %}
{% endif %}
{% if notes.open_questions %}

## Needs attention

{% for q in notes.open_questions %}
- {{ q }}
{% endfor %}
{% endif %}
