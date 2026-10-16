"""Original 15-second, 128 BPM score; deterministic separate stereo stems."""
from pathlib import Path
import wave
import numpy as np

ROOT = Path(__file__).resolve().parents[1] / 'assets'
SR, DUR = 48000, 15
N = SR * DUR
rng = np.random.default_rng(10414)
beat = 60 / 128
stems = {k: np.zeros((N, 2)) for k in ['Rhythm', 'Bass', 'Glass', 'Atmosphere', 'Transitions']}

def add(track, at, sig, gain=1, pan=0):
    start = int(at * SR)
    if start < 0:
        sig = sig[-start:]; start = 0
    n = min(len(sig), N - start)
    if n <= 0: return
    sig = sig[:n] * gain
    stems[track][start:start+n, 0] += sig * np.sqrt((1-pan)/2)
    stems[track][start:start+n, 1] += sig * np.sqrt((1+pan)/2)

def t(n): return np.arange(int(n * SR)) / SR
def tone(freq, length, decay=5):
    q = t(length)
    env = np.minimum(q / .004, 1) * np.exp(-q * decay)
    return (np.sin(2*np.pi*freq*q) + .24*np.sin(2*np.pi*freq*2*q) + .08*np.sin(2*np.pi*freq*3*q))*env

for b in range(30):
    at = b * beat
    if at > 13.5: break
    # Deep tight kick, pitched from 135 to 48 Hz.
    q = t(.32)
    phase = 2*np.pi*(48*q + 87*.028*(1-np.exp(-q/.028)))
    kick = np.sin(phase)*np.exp(-q*14) + .07*rng.normal(0,1,len(q))*np.exp(-q*160)
    add('Rhythm', at, kick, .65)
    if b % 2 == 1:
        q = t(.18); noise = rng.normal(0,1,len(q)); noise = noise - np.roll(noise, 1)*.8
        snare = .35*noise*np.exp(-q*32) + .4*np.sin(2*np.pi*190*q)*np.exp(-q*35)
        add('Rhythm', at, snare, .25, .06)
    for half in (0, .5):
        q=t(.065); noise=rng.normal(0,1,len(q)); noise=np.diff(noise,prepend=0)
        add('Rhythm',at+half*beat,noise*np.exp(-q*85),.048,(-1 if b%2 else 1)*.35)
    bass_freq = [65.406,65.406,73.416,58.270][b//8 % 4]
    add('Bass',at+.015,tone(bass_freq,.37,7),.25)
    if b%4==3: add('Bass',at+.75*beat,tone(bass_freq*2,.13,17),.1)

# Bright minor-ninth arpeggio; wide delay answers add depth.
notes=[261.626,311.127,391.995,466.164,523.251,466.164,391.995,311.127]
for j in range(56):
    at=.18+j*beat/2
    if at>12.9:break
    note=notes[j%8]; sig=tone(note,.7,7.5)
    add('Glass',at,sig,.11, .4*np.sin(j*.8))
    add('Glass',at+.23,sig,.033,-.45*np.sin(j*.8))

# Warm, slowly breathing chord underneath the transient rhythm.
q=t(14.7)
pad=np.zeros(len(q))
for f in [130.813,155.563,195.998,233.082]:
    pad += np.sin(2*np.pi*f*q+.004*np.sin(2*np.pi*.23*q))*.022
pad *= np.minimum(q/1.1,1)*np.minimum((14.7-q)/1.8,1)*(.7+.3*np.sin(2*np.pi*q/beat)**2)
add('Atmosphere',0,pad,1,-.18)
add('Atmosphere',.09,pad,.8,.18)

# Match each iris / wipe and interface reveal with designed sound.
for at in [2.36,5.02,9.18,11.74]:
    q=t(.55); noise=rng.normal(0,1,len(q)); noise=np.convolve(noise,np.ones(18)/18,mode='same')
    sweep=noise*np.sin(np.pi*q/.55)**2
    add('Transitions',at-.28,sweep,.37,-.55)
    add('Transitions',at-.18,sweep,.32,.55)
    q=t(.27); impact=np.sin(2*np.pi*(75*q+38*.04*(1-np.exp(-q/.04))))*np.exp(-q*18)
    add('Transitions',at+.26,impact,.38)
for j,at in enumerate([3.08,3.22,3.36,6.7,6.88,7.06]):
    add('Transitions',at,tone(1400+j*100,.085,45),.04,(-1 if j%2 else 1)*.5)
# Closing three-note sonic signature with a long, soft tail.
for j,f in enumerate([523.251,783.991,1046.502]):
    at=12.64+j*.13; sig=tone(f,1.7,3.4)
    add('Glass',at,sig,.20,[-.25,0,.25][j]); add('Glass',at+.20,sig,.055,.4)

# Every stem has a common end taper, leaving a clean final frame.
fade=np.ones(N); end=int(14.85*SR); fade[end:]=np.linspace(1,0,N-end)
for name,data in stems.items():
    data=np.clip(data*fade[:,None],-.97,.97)
    pcm=(data*32767).astype('<i2')
    with wave.open(str(ROOT / (name.lower()+'.wav')),'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    print(name, 'peak',round(20*np.log10(max(np.abs(data).max(),1e-10)),2),'dBFS')
