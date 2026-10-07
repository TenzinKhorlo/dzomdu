---
name: Board / committee minutes
description: Formal minutes - attendance, agenda items, resolutions and actions.
instructions: >
  Formal register, third person, past tense (e.g. "The committee noted...",
  "Karma Wangmo presented..."). Treat each topic as an agenda item and keep the
  order in which items were discussed. Phrase decisions as resolutions
  ("It was resolved that...").
---
**Date:** {{ meeting.date[:10] }} · **Duration:** {{ meeting.duration }}{% if meeting.project %} · **Project:** [[{{ meeting.project }}]]{% endif %}


## Attendance

{% for name in meeting.attendees %}
- {{ person(name) }}
{% endfor %}
{% for name in meeting.unknown_speakers %}
- {{ name }} (not identified)
{% endfor %}

## Summary

{{ notes.summary }}

{% for t in notes.topics %}
## {{ loop.index }}. {{ t.title }}

{% for p in t.points %}
{{ p }}

{% endfor %}
{% endfor %}
## Resolutions

{% for d in notes.decisions %}
{{ loop.index }}. {{ d.decision }} {{ cite(d) }}
{% else %}
_No resolutions were passed._
{% endfor %}

## Actions arising

| # | Action | Owner | Due |
|---|---|---|---|
{% for a in notes.action_items %}
| {{ loop.index }} | {{ a.task }} {{ cite(a) | replace("|", "\\|") }} | {{ (person(a.owner) if a.owner else "—") | replace("|", "\\|") }} | {{ a.due or "—" }} |
{% endfor %}
{% if notes.next_meeting %}

**Next meeting:** {{ notes.next_meeting }}
{% endif %}
