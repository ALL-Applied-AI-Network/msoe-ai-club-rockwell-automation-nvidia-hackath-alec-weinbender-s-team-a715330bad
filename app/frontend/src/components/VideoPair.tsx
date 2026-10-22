import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "./Button";
import { Checkbox } from "./Field";
import { Segmented } from "./Segmented";
import { usePrefersReducedMotion, VideoPlayer } from "./VideoPlayer";
import styles from "./VideoPair.module.css";

export type PairVideo = {
  src: string;
  label: string; // the text alternative: what it shows, in words
  caption: ReactNode; // under it: the design, the grasp and its outcome
};

const SPEEDS = [
  { value: "1", label: "Full speed" },
  { value: "0.5", label: "Half" },
  { value: "0.25", label: "Quarter" },
];

/** Two short videos side by side, played together: the best design against stock at the same grasp. One set of
 *  controls drives both (play and pause, start again, loop, slow motion), and the second follows the first's time. */
export function VideoPair({ left, right }: { left: PairVideo; right: PairVideo }) {
  const first = useRef<HTMLVideoElement>(null);
  const second = useRef<HTMLVideoElement>(null);
  const reduced = usePrefersReducedMotion();
  const [playing, setPlaying] = useState(false);
  const [loop, setLoop] = useState(true);
  const [speed, setSpeed] = useState("1");

  const both = () => [first.current, second.current].filter((v): v is HTMLVideoElement => v !== null);
  const play = () => {
    for (const video of both()) void video.play();
    setPlaying(true);
  };
  const pause = () => {
    for (const video of both()) video.pause();
    setPlaying(false);
  };
  const restart = () => {
    for (const video of both()) video.currentTime = 0;
    play();
  };

  // New clips: start them together, unless the viewer prefers reduced motion.
  useEffect(() => {
    setPlaying(false);
    if (reduced) return;
    const videos = both();
    let ready = 0;
    const onReady = () => {
      ready += 1;
      if (ready === videos.length) play();
    };
    const waiting = videos.filter((video) => video.readyState < HTMLMediaElement.HAVE_FUTURE_DATA);
    ready = videos.length - waiting.length;
    if (waiting.length === 0) play();
    for (const video of waiting) video.addEventListener("canplay", onReady, { once: true });
    return () => waiting.forEach((video) => video.removeEventListener("canplay", onReady));
  }, [left.src, right.src, reduced]); // play() only reads the refs, so it isn't a dependency

  // Keeps the second clip on the first one's time, and stops both at the end when not looping.
  useEffect(() => {
    const leader = first.current;
    if (!leader) return;
    const sync = () => {
      const follower = second.current;
      if (follower && Math.abs(follower.currentTime - leader.currentTime) > 0.1) follower.currentTime = leader.currentTime;
    };
    const ended = () => setPlaying(false);
    leader.addEventListener("timeupdate", sync);
    leader.addEventListener("ended", ended);
    return () => {
      leader.removeEventListener("timeupdate", sync);
      leader.removeEventListener("ended", ended);
    };
  }, [left.src, right.src]);

  return (
    <div className={styles.pair}>
      <div className={styles.videos}>
        {[left, right].map((video, i) => (
          <VideoPlayer
            key={i}
            src={video.src}
            label={video.label}
            caption={video.caption}
            autoPlay={false}
            playButton={false}
            loop={loop}
            playbackRate={Number(speed)}
            videoRef={i === 0 ? first : second}
          />
        ))}
      </div>
      <div className={styles.controls}>
        <Button variant={playing ? "secondary" : "primary"} size="sm" onClick={playing ? pause : play}>
          {playing ? "Pause both" : "Play both"}
        </Button>
        <Button variant="secondary" size="sm" onClick={restart}>
          Start again
        </Button>
        <Segmented label="Speed" options={SPEEDS} value={speed} onChange={setSpeed} />
        <Checkbox label="Loop" checked={loop} onChange={setLoop} />
      </div>
    </div>
  );
}
