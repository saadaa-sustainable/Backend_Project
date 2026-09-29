// Nested dialogs can unmount together when their analytics section is hidden.
// Restore scrolling only after the last dialog closes, regardless of order.
let locks = 0;
let previousOverflow = "";

export function lockBodyScroll(): () => void {
  if (locks === 0) previousOverflow = document.body.style.overflow;
  locks += 1;
  document.body.style.overflow = "hidden";
  let released = false;
  return () => {
    if (released) return;
    released = true;
    locks -= 1;
    if (locks === 0) document.body.style.overflow = previousOverflow;
  };
}
