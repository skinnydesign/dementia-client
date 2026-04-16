// Alarm sound library — synthesised via Web Audio API (no audio files required)
// Used by base.html for alarm playback and index.html for settings preview.

const ALARM_SOUNDS = [
  { id: 'chime',     label: 'Chime'     },
  { id: 'doorbell',  label: 'Doorbell'  },
  { id: 'telephone', label: 'Telephone' },
  { id: 'cuckoo',    label: 'Cuckoo'    },
  { id: 'beep',      label: 'Beep'      },
  { id: 'silent',    label: 'Silent'    },
];

// Dispatch to the right sound function.
function playAlarmSound(ctx, sound) {
  if (!ctx || sound === 'silent') return;
  switch (sound) {
    case 'chime':     _alarmChime(ctx);     break;
    case 'doorbell':  _alarmDoorbell(ctx);  break;
    case 'telephone': _alarmTelephone(ctx); break;
    case 'cuckoo':    _alarmCuckoo(ctx);    break;
    case 'beep':      _alarmBeep(ctx);      break;
  }
}

// C5–E5–G5–C6 ascending sine arpeggio (original chime)
function _alarmChime(ctx) {
  [523.25, 659.25, 783.99, 1046.50].forEach((freq, i) => {
    const osc  = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    osc.type = 'sine'; osc.frequency.value = freq;
    const t = ctx.currentTime + i * 0.18;
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.4, t + 0.05);
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.55);
    osc.start(t); osc.stop(t + 0.6);
  });
}

// Classic ding-dong doorbell: E5 then C5
function _alarmDoorbell(ctx) {
  [[659.25, 0], [523.25, 0.45]].forEach(([freq, when]) => {
    const osc  = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    osc.type = 'sine'; osc.frequency.value = freq;
    const t = ctx.currentTime + when;
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.5, t + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.8);
    osc.start(t); osc.stop(t + 0.85);
  });
}

// Old telephone: two bursts of 400 Hz + 450 Hz square waves, pulsed at 25 Hz
function _alarmTelephone(ctx) {
  [0, 0.6].forEach(ringStart => {
    [400, 450].forEach(freq => {
      const osc  = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.type = 'square'; osc.frequency.value = freq;
      const dur = 0.45, pulseLen = 1 / 25; // 25 Hz mechanical-bell pulse
      const t0  = ctx.currentTime + ringStart;
      for (let t = t0; t < t0 + dur; t += pulseLen) {
        gain.gain.setValueAtTime(0.12, t);
        gain.gain.setValueAtTime(0,    t + pulseLen * 0.5);
      }
      osc.start(t0); osc.stop(t0 + dur + 0.02);
    });
  });
}

// Cuckoo clock: G5–E5 twice, triangle wave
function _alarmCuckoo(ctx) {
  [[783.99, 0], [659.25, 0.22], [783.99, 0.56], [659.25, 0.78]].forEach(([freq, when]) => {
    const osc  = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    osc.type = 'triangle'; osc.frequency.value = freq;
    const t = ctx.currentTime + when;
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.4, t + 0.04);
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.2);
    osc.start(t); osc.stop(t + 0.22);
  });
}

// Digital alarm: three short 880 Hz square beeps
function _alarmBeep(ctx) {
  [0, 0.28, 0.56].forEach(when => {
    const osc  = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    osc.type = 'square'; osc.frequency.value = 880;
    const t = ctx.currentTime + when;
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.25, t + 0.01);
    gain.gain.setValueAtTime(0.25, t + 0.16);
    gain.gain.linearRampToValueAtTime(0, t + 0.18);
    osc.start(t); osc.stop(t + 0.2);
  });
}

// One-shot preview used by the settings page.
function previewAlarmSound(sound) {
  if (sound === 'silent') return;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === 'suspended') ctx.resume();
    playAlarmSound(ctx, sound);
    setTimeout(() => { try { ctx.close(); } catch(e) {} }, 3000);
  } catch(e) {}
}
