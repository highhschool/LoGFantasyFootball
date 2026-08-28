import { SignIn } from "./SignIn";
import { Modal } from "./Modal";
import type { KeeperManager } from "../types";

/**
 * Signing in over whatever you were doing.
 *
 * Every place that needs an account is a place somebody was already partway
 * through something -- importing a league, buying a contract, choosing a
 * keeper. A dialog keeps that page underneath rather than rearranging it.
 */
export function SignInDialog({
  title = "Sign in",
  blurb,
  onSignedIn,
  onClose,
}: {
  title?: string;
  blurb?: string;
  onSignedIn: (manager: KeeperManager) => void;
  onClose: () => void;
}) {
  return (
    <Modal title={title} onClose={onClose}>
      <SignIn blurb={blurb} onSignedIn={onSignedIn} />
    </Modal>
  );
}
