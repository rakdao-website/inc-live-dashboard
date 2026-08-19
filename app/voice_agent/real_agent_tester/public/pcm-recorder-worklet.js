// Runs on the audio rendering thread, not the main thread - just hands raw
// Float32 samples back to main.js via postMessage, one render quantum
// (usually 128 samples) at a time. Conversion to PCM16 and the actual
// decision of whether to send it anywhere happens in main.js, since that's
// where the mute flag and the session live.
class PCMRecorderProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input && input[0] && input[0].length > 0) {
      // Copy the buffer - the original gets reused/cleared by the audio
      // engine right after this call returns.
      this.port.postMessage(input[0].slice());
    }
    return true; // keep the processor alive for the next quantum
  }
}

registerProcessor("pcm-recorder-processor", PCMRecorderProcessor);