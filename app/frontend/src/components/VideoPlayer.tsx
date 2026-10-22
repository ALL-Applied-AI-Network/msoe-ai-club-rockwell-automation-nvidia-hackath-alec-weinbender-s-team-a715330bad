import { useCallback, useEffect, useRef, useState, type ReactNode, type Ref } from "react";
import { Button } from "./Button";
import styles from "./VideoPlayer.module.css";

type VideoPlayerProps = {
  src: string;
  poster?: string; // a still, shown before it plays and instead of autoplay for reduced motion
  label: string; // the text alternative: what the video shows, in words
  caption?: ReactNode; // a line under it, e.g. "Example in Isaac Sim: ..." or a clip's offset and outcome
  autoPlay?: boolean; // muted and inline, unless the viewer prefers reduced motion
  loop?: boolean;
  playbackRate?: number; // 0.25 to 1: slow motion
  videoRef?: Ref<HTMLVideoElement>; // for a parent that drives playback, e.g. two clips played together
  playButton?: boolean; // the Play button over the still when it doesn't autoplay; off when a parent has its own
};

/** A short silent video: the task step's Isaac Sim examples, and the recorded clips on the results page. Autoplays
 *  muted and looping, except for viewers who prefer reduced motion, who get the still and a Play button. */
export function VideoPlayer({
  src,
  poster,
  label,
  caption,
  autoPlay = true,
  loop = true,
  playbackRate = 1,
  videoRef,
  playButton = true,
}: VideoPlayerProps) {
  const ref = useRef<HTMLVideoElement | null>(null);
  const reduced = usePrefersReducedMotion();
  const [playing, setPlaying] = useState(false);
  const play = autoPlay && !reduced;

  // Keeps our own ref and hands the element to the parent's too.
  const setRef = useCallback(
    (element: HTMLVideoElement | null) => {
      ref.current = element;
      if (typeof videoRef === "function") videoRef(element);
      else if (videoRef) videoRef.current = element;
    },
    [videoRef],
  );

  useEffect(() => {
    ref.current?.load(); // a new src: start it again
  }, [src]);

  useEffect(() => {
    if (ref.current) ref.current.playbackRate = playbackRate;
  }, [playbackRate, src]);

  return (
    <figure className={styles.figure}>
      <div className={styles.frame}>
        <video
          ref={setRef}
          className={styles.video}
          src={src}
          poster={poster}
          aria-label={label}
          muted
          loop={loop}
          playsInline
          autoPlay={play}
          preload={play ? "auto" : "metadata"}
          onLoadedMetadata={(event) => (event.currentTarget.playbackRate = playbackRate)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        >
          {label}
        </video>
        {playButton && !play && !playing && (
          <div className={styles.overlay}>
            <Button variant="secondary" onClick={() => void ref.current?.play()}>
              Play
            </Button>
          </div>
        )}
      </div>
      {caption && <figcaption className={styles.caption}>{caption}</figcaption>}
    </figure>
  );
}

/** Whether the viewer asked for less motion: nothing autoplays for them. */
export function usePrefersReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const list = window.matchMedia(query);
    const onChange = () => setReduced(list.matches);
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  }, []);
  return reduced;
}
