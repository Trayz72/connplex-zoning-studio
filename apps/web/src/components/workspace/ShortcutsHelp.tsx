import React, { useEffect } from 'react';

const SEEN_KEY = 'cz-edit-onboarding-seen';

const SHORTCUTS: { keys: string; does: string }[] = [
  { keys: 'Delete / Backspace', does: 'Delete the selected room' },
  { keys: 'Escape', does: 'Deselect the current room' },
  { keys: 'Ctrl/Cmd + Z', does: 'Undo the last edit' },
  { keys: 'Ctrl/Cmd + Shift + Z', does: 'Redo' },
  { keys: 'Scroll / trackpad', does: 'Zoom, centered on the cursor' },
  { keys: 'Drag empty space', does: 'Pan the canvas' },
  { keys: 'Drag a room', does: 'Move it' },
  { keys: 'Drag a white handle', does: 'Resize the selected room' }
];

/** Has the user already dismissed the first-run onboarding for the Edit
 * step, in this browser? Same plain localStorage pattern as theme.ts. */
export function hasSeenEditOnboarding(): boolean {
  try {
    return localStorage.getItem(SEEN_KEY) === '1';
  } catch {
    return true; // private-browsing/storage-blocked: don't nag every load
  }
}

function markEditOnboardingSeen() {
  try {
    localStorage.setItem(SEEN_KEY, '1');
  } catch {
    // best-effort only
  }
}

interface Props {
  /** True the first time this renders in a fresh session for this browser —
   * shows a short welcome framing instead of just a bare shortcuts table. */
  isFirstRun: boolean;
  onClose: () => void;
}

export const ShortcutsHelp: React.FC<Props> = ({ isFirstRun, onClose }) => {
  useEffect(() => {
    markEditOnboardingSeen();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 1000,
        display: 'flex', alignItems: 'center', justifyContent: 'center'
      }}
      onClick={onClose}
    >
      <div
        className="panel"
        style={{ maxWidth: '420px', width: '90%', padding: '20px', boxShadow: 'var(--shadow-lg)', background: 'var(--bg-raised)' }}
        onClick={(e) => e.stopPropagation()}
      >
        {isFirstRun ? (
          <>
            <div style={{ fontSize: 'var(--text-lg)', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
              Welcome to the Edit canvas
            </div>
            <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', marginBottom: '14px', lineHeight: 1.5 }}>
              Drag rooms to move them, drag a handle to resize. Add Foyer, F&amp;B, Washroom, Box Office, Back-of-House, or another Screen from the toolbar above. Everything below works too:
            </div>
          </>
        ) : (
          <div style={{ fontSize: 'var(--text-lg)', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '14px' }}>
            Keyboard &amp; Mouse Shortcuts
          </div>
        )}
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' }}>
          <tbody>
            {SHORTCUTS.map(s => (
              <tr key={s.keys} style={{ borderTop: '1px solid var(--border-color)' }}>
                <td className="font-mono" style={{ padding: '6px 8px 6px 0', color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>{s.keys}</td>
                <td style={{ padding: '6px 0', color: 'var(--text-secondary)' }}>{s.does}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="btn btn-primary btn-sm" style={{ marginTop: '16px', width: '100%' }} onClick={onClose}>
          Got it
        </button>
      </div>
    </div>
  );
};
