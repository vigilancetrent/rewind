# rewind

> **Chrome DevTools for AI agents.** Record any agent run. Scrub through every tool call, prompt, and token. Replay from any step with a different model. Local-first, single SQLite file, zero cloud.

```
pip install rewind
```

Three lines to record any agent. One command to scrub through it. One flag to replay it with a different model.

---

## 30-second quickstart

```python
import rewind
import anthropic

client = anthropic.Anthropic()

with rewind.record("contract-review-2026-05-05"):
    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Summarise this contract..."}],
    )
    # ...your agent loops, tool calls, follow-ups — all captured
```

Then from your terminal:

```
$ rewind list
contract-review-2026-05-05   14 calls   $0.42   2026-05-05 11:42

$ rewind scrub contract-review-2026-05-05
```

```
┌─ rewind: contract-review-2026-05-05 ─────────────────────────────────┐
│ STEPS                       │ STEP 7 of 14                           │
│ ▸ 0  claude-opus       91   │ provider: anthropic                    │
│   1  tool: search      12   │ model:    claude-opus-4-7              │
│   2  tool: read_file   45   │ tokens:   input=4,231  output=812      │
│ ▶ 7  claude-opus      183   │ cost:     $0.06   latency: 1,840 ms    │
│   8  tool: web_fetch    3   │                                        │
│   9  claude-haiku      77   │ messages:                              │
│  ...                        │   [user]    "Summarise contract..."    │
│                             │   [tool]    {"path": "nda.pdf"}        │
│                             │   [model]   "The contract..."          │
└─ q quit · e export · r replay from here ─────────────────────────────┘
```

## Replay from any step — with a different model

```
$ rewind replay demo-run --from-step=7 --model=claude-haiku-4-5-20251001
```

`rewind` walks the trace from step 7 onward, swaps the model, and writes a new trace you can scrub side-by-side with the original.

## What if my agent doesn't use anthropic/openai/ollama?

```python
import rewind, time

with rewind.record("my-custom-agent") as r:
    t0 = time.time()
    response = my_weird_provider.generate(prompt)
    r.log_call(rewind.ProviderCall(
        step=0,
        timestamp=t0,
        provider="custom",
        model="my-llm-v2",
        messages=[{"role": "user", "content": prompt}],
        response_text=response.text,
        input_tokens=response.usage.input,
        output_tokens=response.usage.output,
        latency_ms=(time.time() - t0) * 1000,
    ))
```

## How is this different from...

| Tool | rewind | LangSmith | Weights & Biases | `print(json.dumps(...))` |
|------|--------|-----------|------------------|--------------------------|
| Local-first, no cloud | yes | no | no | yes |
| Interactive scrubber | yes | dashboard | dashboard | no |
| Replay from step N | yes | no | no | no |
| Model swap on replay | yes | no | no | no |
| Single SQLite file | yes | no | no | no |
| Zero account / API key | yes | no | no | yes |

## Built-in integrations

- `anthropic` (>= 0.30)
- `openai` (>= 1.0)
- `ollama` (HTTP client)

## CLI

```
rewind list
rewind scrub <name>
rewind replay <name> [--from-step N] [--model MODEL] [--provider PROVIDER]
rewind export <name> --format=jsonl|html|md
rewind delete <name>
```

All traces live in `~/.rewind/traces.sqlite`.

## License

MIT. (c) 2026 thechifura and rewind contributors.

Sibling project to [vigilancetrent](https://github.com/vigilancetrent) and [strategos](https://github.com/vigilancetrent/strategos).
