// Voix WebRTC en maillage (mesh) + spatialisation Web Audio :
// PannerNode (linéaire, 8 m → 20 m), BiquadFilter passe-bas 400 Hz derrière un mur,
// coupure radio des joueurs capturés.
export class Voice {
  constructor(send) {
    this.send = send;
    this.peers = new Map();
    this.ctx = null;
    this.local = null;
    this.muted = false;
    this.iceServers = [{ urls: 'stun:stun.l.google.com:19302' }];
    fetch('/config').then((r) => r.json()).then((c) => (this.iceServers = c.iceServers)).catch(() => {});
    this.volTimer = null;
    this.lastVol = 0;
  }

  ensureCtx() {
    if (!this.ctx) this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (this.ctx.state === 'suspended') this.ctx.resume();
    return this.ctx;
  }

  async enableMic() {
    this.ensureCtx();
    this.local = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const track = this.local.getAudioTracks()[0];
    for (const peer of this.peers.values()) peer.sender?.replaceTrack(track);
    const analyser = this.ctx.createAnalyser();
    analyser.fftSize = 512;
    this.ctx.createMediaStreamSource(this.local).connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    clearInterval(this.volTimer);
    this.volTimer = setInterval(() => {
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += v * v;
      const vol = this.muted ? 0 : Math.min(1, Math.sqrt(sum / buf.length) * 6);
      this.level = vol;
      if (Math.abs(vol - this.lastVol) > 0.04) { this.lastVol = vol; this.send({ t: 'vol', v: vol }); }
    }, 200);
    return true;
  }

  setMuted(m) {
    this.muted = m;
    this.local?.getAudioTracks().forEach((t) => (t.enabled = !m));
  }

  // Annonce une nouvelle session : les pairs ferment leurs connexions obsolètes.
  hello(ids) { for (const id of ids) if (id !== this.me) this.send({ t: 'rtc', to: id, data: { hello: true } }); }

  sync(me, ids) {
    this.me = me;
    for (const id of this.peers.keys()) if (!ids.includes(id)) this.drop(id);
    for (const id of ids) if (id !== me && !this.peers.has(id) && me < id) this.create(id, true);
  }

  create(id, initiator) {
    const pc = new RTCPeerConnection({ iceServers: this.iceServers });
    const peer = { pc, pending: [], sender: null, nodes: null };
    this.peers.set(id, peer);
    if (initiator) {
      const tr = pc.addTransceiver('audio', { direction: 'sendrecv' });
      peer.sender = tr.sender;
      if (this.local) tr.sender.replaceTrack(this.local.getAudioTracks()[0]);
    }
    pc.onicecandidate = (e) => e.candidate && this.send({ t: 'rtc', to: id, data: { candidate: e.candidate } });
    pc.ontrack = (e) => this.attach(peer, e.streams[0] || new MediaStream([e.track]));
    pc.onconnectionstatechange = () => {
      if (['failed', 'closed'].includes(pc.connectionState) && this.peers.get(id) === peer) this.drop(id);
    };
    if (initiator) {
      pc.createOffer()
        .then((o) => pc.setLocalDescription(o))
        .then(() => this.send({ t: 'rtc', to: id, data: { sdp: pc.localDescription } }))
        .catch(() => this.drop(id));
    }
    return peer;
  }

  drop(id) {
    const peer = this.peers.get(id);
    if (!peer) return;
    this.peers.delete(id);
    peer.pc.close();
    peer.nodes?.el.remove();
    peer.nodes?.panner.disconnect();
  }

  async onSignal(from, data) {
    if (data.hello) return this.drop(from);
    let peer = this.peers.get(from);
    try {
      if (data.sdp) {
        if (data.sdp.type === 'offer') {
          if (peer) this.drop(from);
          peer = this.create(from, false);
        }
        if (!peer) return;
        await peer.pc.setRemoteDescription(data.sdp);
        for (const c of peer.pending) await peer.pc.addIceCandidate(c);
        peer.pending = [];
        if (data.sdp.type === 'offer') {
          const tr = peer.pc.getTransceivers()[0];
          if (tr) {
            tr.direction = 'sendrecv';
            peer.sender = tr.sender;
            if (this.local) await tr.sender.replaceTrack(this.local.getAudioTracks()[0]);
          }
          await peer.pc.setLocalDescription(await peer.pc.createAnswer());
          this.send({ t: 'rtc', to: from, data: { sdp: peer.pc.localDescription } });
        }
      } else if (data.candidate && peer) {
        if (peer.pc.remoteDescription) await peer.pc.addIceCandidate(data.candidate);
        else peer.pending.push(data.candidate);
      }
    } catch (e) {
      console.warn('[voice] signal', e);
    }
  }

  attach(peer, stream) {
    const ctx = this.ensureCtx();
    // Contournement Chrome : un flux WebRTC distant doit être lu par un élément média.
    const el = new Audio();
    el.srcObject = stream;
    el.muted = true;
    el.play().catch(() => {});
    const src = ctx.createMediaStreamSource(stream);
    const filter = ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.value = 22050;
    const gain = ctx.createGain();
    const panner = ctx.createPanner();
    Object.assign(panner, { panningModel: 'HRTF', distanceModel: 'linear', refDistance: 8, maxDistance: 20, rolloffFactor: 1 });
    src.connect(filter).connect(gain).connect(panner).connect(ctx.destination);
    peer.nodes = { el, filter, gain, panner };
  }

  // Appelé à chaque image : positionne l'auditeur et chaque source.
  update({ state, me, pos, geo }) {
    if (!this.ctx || !state) return;
    const t = this.ctx.currentTime;
    const L = this.ctx.listener;
    const inGame = ['CLUE', 'FIELD', 'EXTRACTION'].includes(state.phase);
    const spatial = inGame && me && me.publicRole === 'field' && me.alive;
    const lx = spatial ? pos.x : 0, lz = spatial ? pos.y : 0;
    const fx = Math.cos(spatial ? pos.a : 0), fz = Math.sin(spatial ? pos.a : 0);
    if (L.positionX) {
      L.positionX.setValueAtTime(lx, t); L.positionY.setValueAtTime(0, t); L.positionZ.setValueAtTime(lz, t);
      L.forwardX.setValueAtTime(fx, t); L.forwardY.setValueAtTime(0, t); L.forwardZ.setValueAtTime(fz, t);
      L.upX.setValueAtTime(0, t); L.upY.setValueAtTime(1, t); L.upZ.setValueAtTime(0, t);
    } else {
      L.setPosition(lx, 0, lz);
      L.setOrientation(fx, 0, fz, 0, 1, 0);
    }
    for (const [id, peer] of this.peers) {
      const n = peer.nodes;
      if (!n) continue;
      const p = state.players.find((q) => q.id === id);
      let g = p?.connected ? 1 : 0, px = lx, pz = lz, cutoff = 22050;
      if (p && inGame) {
        if (p.publicRole === 'operator') g = 0; // Opérateur cloîtré : communication par indices uniquement.
        else if (!p.alive) g = me?.alive || me?.publicRole === 'operator' ? 0 : 1; // Coupure radio.
        else if (spatial) {
          px = p.x; pz = p.y;
          if (!geo.los(pos.x, pos.y, p.x, p.y)) cutoff = 400;
        }
      }
      if (n.panner.positionX) {
        n.panner.positionX.setValueAtTime(px, t); n.panner.positionY.setValueAtTime(0, t); n.panner.positionZ.setValueAtTime(pz, t);
      } else n.panner.setPosition(px, 0, pz);
      n.filter.frequency.setTargetAtTime(cutoff, t, 0.08);
      n.gain.gain.setTargetAtTime(g, t, 0.03);
    }
  }

  closeAll() { for (const id of [...this.peers.keys()]) this.drop(id); }
}
