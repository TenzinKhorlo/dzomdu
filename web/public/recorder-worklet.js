// Runs on the audio thread: downmixes to mono, downsamples to 16 kHz (averaging each output
// sample's input window, which also acts as a simple low-pass filter) and posts 16-bit PCM
// chunks of ~250 ms with their RMS level.
class PCMRecorder extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.ratio = sampleRate / (options.processorOptions.targetRate || 16000);
    this.acc = 0;
    this.sum = 0;
    this.n = 0;
    this.out = new Int16Array(4000);
    this.len = 0;
    this.sq = 0;
    this.port.onmessage = (e) => { if (e.data === "flush") this.flush(); };
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const channels = input.length;
    const frames = input[0].length;
    for (let i = 0; i < frames; i++) {
      let v = 0;
      for (let c = 0; c < channels; c++) v += input[c][i];
      this.sum += v / channels;
      this.n += 1;
      this.acc += 1;
      if (this.acc >= this.ratio) {
        this.acc -= this.ratio;
        const s = Math.max(-1, Math.min(1, this.sum / this.n));
        this.sum = 0;
        this.n = 0;
        this.out[this.len++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        this.sq += s * s;
        if (this.len === this.out.length) this.flush();
      }
    }
    return true;
  }

  flush() {
    if (this.len === 0) return;
    const pcm = this.out.slice(0, this.len).buffer;
    const rms = Math.sqrt(this.sq / this.len);
    this.port.postMessage({ pcm, rms }, [pcm]);
    this.len = 0;
    this.sq = 0;
  }
}

registerProcessor("pcm-recorder", PCMRecorder);
