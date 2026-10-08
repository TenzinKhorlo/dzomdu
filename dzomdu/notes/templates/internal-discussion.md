---
name: Internal discussion
description: Header line, attendees with roles, purpose, key takeaways, labelled topics, comments and actions.
instructions: >
  Write in clear, neutral English. Each key takeaway has a short headline (3-6 words) and one or
  two sentences. For every topic, write its points in this order, using these exact labels and
  leaving out any that do not apply: "Problem: ...", "Decision: ...", "Rationale: ...",
  "Path Forward: ...". Other facts a topic needs go in extra points without a label. Put
  conditions, approvals and requests raised in the "comments" field, not in the topics.
sections:
  meeting_type:
    title: Meeting type
    type: text
    description: The kind of meeting in two or three words, for example Internal Discussion, Client Meeting, Board Meeting or Weekly Sync.
  purpose:
    title: Meeting purpose
    type: text
    description: One sentence on what the meeting set out to achieve.
  key_takeaways:
    title: Key takeaways
    type: items
    description: The three to five most important outcomes. Each has a short headline as "title" and one or two sentences as "text".
  comments:
    title: Comments
    type: list
    description: Conditions, approvals required, requests and other remarks that are neither decisions nor action items. Empty if there are none.
---
**{{ notes.extra.meeting_type or "Meeting" }} • {{ meeting.date_long }} • {{ meeting.minutes }} min{{ "s" if meeting.minutes != 1 }}**

## Attendee

{% for name in meeting.attendees %}
{% set r = role(name) %}
{{ loop.index }}. {% if r %}{{ r }} {% endif %}{{ person(name) }}
{% endfor %}
{% for name in meeting.unknown_speakers %}
- {{ name }} (not identified)
{% endfor %}

## Meeting purpose

{{ notes.extra.purpose or notes.summary }}

## Key takeaways

{% for k in notes.extra.key_takeaways %}
* **{{ k.title }}:** {{ k.text }}
{% else %}
* {{ notes.summary }}
{% endfor %}

## Topics

{% for t in notes.topics %}
{{ loop.index }}. {{ t.title }} {{ cite(t) }}
{% for p in t.points %}
   {{ loop.index }}. {{ p }}
{% endfor %}
{% endfor %}
{% if notes.extra.comments %}

## Comments

{% for c in notes.extra.comments %}
{{ loop.index }}. {{ c }}
{% endfor %}
{% endif %}

## Action items

{% for a in notes.action_items %}
* [ ] {{ task(a) }}
{% else %}
* _No action items recorded._
{% endfor %}
{% if notes.open_questions %}

## Open questions

{% for q in notes.open_questions %}
- {{ q }}
{% endfor %}
{% endif %}
