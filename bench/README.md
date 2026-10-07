# Phase 0 benchmarks

The goal is to choose models and thresholds based on **your** rooms, microphones and people,
not on published leaderboards. Plan on about a day of labelling for a solid result.

## 1. Record test meetings

Aim for **5–10 real meetings** that cover the situations you care about:

- **Microphones:** a laptop mic and a speakerphone.
- **Group size:** 2–8 people.
- **Room size:** small and large rooms.
- **Talk style:** some meetings with interruptions and crosstalk.
- **The same people across meetings.** This matters most: speaker recognition can only be
  measured across meetings.

Get everyone's consent before recording. Put the files in `bench/data/`; git ignores audio
files there.

## 2. Label who spoke when

Label 2–4 meetings fully, or at least 10–15 minutes of each.

1. Open the recording in [Audacity](https://www.audacityteam.org/).
2. Select each stretch where one person speaks and press **Ctrl/Cmd+B**.
3. Type the person's **real name**, spelled the same way in every meeting.
4. **File → Export → Export Labels…** saves `m01.labels.txt`.

Overlapping speech can have overlapping labels. Skip silences.

## 3. (Optional) Reference transcripts for WER

Run `dzomdu process` with `--no-llm`, copy the transcript text, and **correct it by hand**
while listening. Save it as `m01.txt`. A few 10-minute excerpts are enough.

Correcting one model's output slightly favours that model. To be fair to all models,
correct the output of a model you are *not* comparing.

## 4. Run

```bash
cp bench/manifest.example.yaml bench/manifest.yaml   # edit paths
uv run dzomdu bench all -m bench/manifest.yaml -o bench_out
# or one at a time: asr | diarization | speaker-id | llm
```

The results go to `bench_out/report.md`.

## 5. What to decide from the report

| Section | Look at | Decision |
|---|---|---|
| ASR | Overall WER and speed per backend | `[asr] backend`. Prefer the fastest one within ~1% WER of the best. |
| Diarization | DER and its split into missed / false alarm / confusion; laptop vs speakerphone | Whether to recommend a speakerphone. A high *confusion* share means voices are being mixed up, so giving `--num-speakers` or the attendee list helps. |
| Speaker ID | Same-person vs different-person similarity; suggested thresholds; leave-one-meeting-out accuracy | Copy the suggested `[speakers]` thresholds into your config. |
| LLM | Read `bench_out/llm/<meeting>/A.md, B.md…` **before** opening the key | `[llm] model`. Accuracy (nothing invented, correct owners) matters more than style. |

Diarization DER on a laptop mic in a real room is typically 10–25%. Above that, the
microphone is usually the problem, not the model.
