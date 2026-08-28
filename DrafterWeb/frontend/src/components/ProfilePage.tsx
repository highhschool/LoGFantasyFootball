import { useRef, useState } from "react";
import { ApiError, me } from "../api";
import type { Profile } from "../types";
import { Avatar } from "./Avatar";
import { SignIn } from "./SignIn";

/** How large an uploaded picture is redrawn before it is sent. */
const EDGE = 256;
const QUALITY = 0.82;

/**
 * Shrink and re-encode a chosen file in the browser.
 *
 * Two jobs, and the second matters more. It caps the size whatever somebody
 * picks -- a 12 megapixel phone photo lands at a few tens of kilobytes -- and
 * it turns the file into plain raster pixels, so an SVG carrying a script
 * arrives at the server as a rectangle of colours. The server checks again
 * anyway: a guard that lives in the page is a courtesy, not a control.
 */
function shrink(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();

    img.onload = () => {
      URL.revokeObjectURL(url);
      const side = Math.min(img.width, img.height);
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = EDGE;

      const ctx = canvas.getContext("2d");
      if (!ctx) return reject(new Error("this browser cannot resize images"));

      // Centre-crop to a square, since it is drawn in a circle either way.
      ctx.drawImage(
        img,
        (img.width - side) / 2,
        (img.height - side) / 2,
        side,
        side,
        0,
        0,
        EDGE,
        EDGE,
      );
      resolve(canvas.toDataURL("image/jpeg", QUALITY));
    };

    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("that file is not an image this browser can read"));
    };
    img.src = url;
  });
}

/**
 * Your profile.
 *
 * Reachable from the top of every screen rather than from inside the keeper
 * tool, because who you are is not one tool's business.
 */
export function ProfilePage({
  profile,
  onChanged,
  onBack,
}: {
  profile: Profile | null;
  onChanged: (next: Profile | null) => void;
  onBack: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  async function upload(chosen: File) {
    setBusy(true);
    setError(null);
    try {
      onChanged((await me.setPhoto(await shrink(chosen))).you);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
      if (file.current) file.current.value = "";
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      onChanged((await me.clearPhoto()).you);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-2xl flex-col gap-6 overflow-y-auto p-6">
      <header className="flex flex-col gap-2">
        <button
          type="button"
          onClick={onBack}
          className="self-start text-sm font-medium text-ink-3 hover:text-ink"
        >
          ← Tools
        </button>
        <h1 className="text-3xl font-semibold tracking-tight">Profile</h1>
      </header>

      {!profile || switching ? (
        <SignIn
          heading={profile ? "Sign in as somebody else" : "Who are you?"}
          blurb={
            profile
              ? "Entering another manager's code moves this browser to them."
              : "Find your name and enter the code you were sent."
          }
          onSignedIn={(who) => {
            setSwitching(false);
            me.get().then((r) => onChanged(r.you));
            void who;
          }}
        />
      ) : (
        <>
          <section className="flex items-center gap-4 rounded-lg border border-rule bg-surface p-5">
            <Avatar profile={profile} size="lg" />
            <div className="min-w-0">
              <p className="text-lg font-semibold">{profile.display_name}</p>
              <p className="text-sm text-ink-3">
                {profile.team_name || "no team name set"}
                {profile.draft_slot ? ` · draft slot ${profile.draft_slot}` : ""}
              </p>
            </div>
          </section>

          <section className="flex flex-col gap-3 rounded-lg border border-rule bg-surface p-5">
            <div>
              <h2 className="text-sm font-semibold tracking-wider text-ink-3 uppercase">
                Picture
              </h2>
              <p className="mt-1 text-sm text-ink-3">
                {profile.custom
                  ? "Your own, replacing the one from Sleeper."
                  : profile.avatar_url
                    ? "Currently your Sleeper avatar. Upload one to replace it."
                    : "Sleeper has no avatar for you, so your initials are shown."}
              </p>
            </div>

            <input
              ref={file}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(e) => {
                const chosen = e.target.files?.[0];
                if (chosen) upload(chosen);
              }}
            />

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => file.current?.click()}
                className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-ground disabled:opacity-50"
              >
                {busy ? "Saving…" : profile.custom ? "Choose another" : "Upload a picture"}
              </button>
              {profile.custom && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={remove}
                  className="rounded-md bg-raised px-4 py-2 text-sm font-semibold text-ink-2 disabled:opacity-50"
                >
                  Use my Sleeper avatar
                </button>
              )}
            </div>

            <p className="text-xs text-ink-3">
              Resized to {EDGE}px square before it leaves your device, and only
              the league sees it.
            </p>
          </section>

          <section className="flex flex-wrap items-center gap-3 rounded-lg border border-rule bg-surface p-5">
            <p className="text-sm text-ink-3">
              Signed in on this device. There is no sign-out — entering another
              manager's code moves this browser to them.
            </p>
            <button
              type="button"
              onClick={() => setSwitching(true)}
              className="rounded-md bg-raised px-3 py-1.5 text-xs font-semibold text-ink-2"
            >
              Sign in as somebody else
            </button>
          </section>
        </>
      )}

      {error && <p className="text-sm text-danger">{error}</p>}
    </div>
  );
}
