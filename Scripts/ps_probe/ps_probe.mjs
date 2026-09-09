// Headless Pixel Streaming player probe: subscribes to the first streamer and
// counts received video RTP for N seconds. Exit 0 = video flowing, 2 = none.
import WebSocket from 'ws';
import { RTCPeerConnection } from 'werift';

const url = process.argv[2] ?? 'ws://127.0.0.1:8080';
const seconds = Number(process.argv[3] ?? 10);
const ws = new WebSocket(url);
let pc = null;
let videoPackets = 0, videoBytes = 0, audioPackets = 0;

const send = (o) => ws.send(JSON.stringify(o));
ws.on('open', () => send({ type: 'listStreamers' }));
ws.on('error', (e) => { console.log('WS ERROR', e.message); process.exit(1); });
ws.on('message', async (data) => {
  const msg = JSON.parse(data.toString());
  if (msg.type === 'streamerList') {
    if (!msg.ids?.length) { console.log('RESULT no_streamers'); process.exit(1); }
    console.log('probe: subscribing to', msg.ids[0]);
    send({ type: 'subscribe', streamerId: msg.ids[0] });
  } else if (msg.type === 'offer') {
    pc = new RTCPeerConnection({});
    pc.onIceCandidate.subscribe((c) => {
      send({ type: 'iceCandidate', candidate: { candidate: c.candidate, sdpMid: c.sdpMid, sdpMLineIndex: c.sdpMLineIndex } });
    });
    pc.ontrack = (e) => {
      const track = e.track;
      console.log('probe: track added kind=' + track.kind);
      track.onReceiveRtp.subscribe((rtp) => {
        if (track.kind === 'video') { videoPackets++; videoBytes += rtp.payload.length; }
        else { audioPackets++; }
      });
    };
    await pc.setRemoteDescription({ type: 'offer', sdp: msg.sdp });
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);
    send({ type: 'answer', sdp: pc.localDescription.sdp });
    setTimeout(() => {
      console.log(`RESULT video_rtp_packets=${videoPackets} video_kb=${(videoBytes / 1024).toFixed(1)} audio_rtp_packets=${audioPackets}`);
      process.exit(videoPackets > 0 ? 0 : 2);
    }, seconds * 1000);
  } else if (msg.type === 'iceCandidate' && pc && msg.candidate) {
    await pc.addIceCandidate(msg.candidate);
  }
});
setTimeout(() => { console.log('RESULT timeout_no_offer'); process.exit(1); }, 20000);
