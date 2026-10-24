import { useState, useEffect, useRef } from 'react'
import { useAuth } from '../context/AuthContext'
import { apiFetch } from '../api/client'
import './NotificationBell.css'

export default function NotificationBell({ onAccept }) {
  const { user, addToContinueWatching } = useAuth()
  const [invites, setInvites] = useState([])
  const [open, setOpen]       = useState(false)
  const bellRef = useRef(null)

  useEffect(() => {
    if (!user?.email) return
    const poll = async () => {
      try {
        const res  = await apiFetch('/invite/pending')
        if (!res.ok) return
        const data = await res.json()
        setInvites(data.invites || [])
      } catch {}
    }
    poll()
    const interval = setInterval(poll, 8000)
    return () => clearInterval(interval)
  }, [user?.email])

  useEffect(() => {
    const handler = (e) => {
      if (bellRef.current && !bellRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const respond = async (inviteId, action, invite) => {
    try {
      const res  = await apiFetch('/invite/respond', {
        method: 'POST',
        body: { invite_id: inviteId, action },
      })
      const data = await res.json()
      setInvites(prev => prev.filter(i => i.id !== inviteId))

      if (action === 'accepted' && data.room_id) {
        // Add movie to accepting user's Continue Watching
        const movieCard = {
          item_id:     invite.movie_id,
          item_idx:    -1,
          title:       invite.movie_title,
          release_year: null,
          genres:      [],
          log_popularity: 0,
        }
        addToContinueWatching(movieCard)

        onAccept({
          roomId:     data.room_id,
          movieId:    invite.movie_id,
          movieTitle: invite.movie_title,
        })
        setOpen(false)
      }
    } catch (e) { console.error(e) }
  }

  return (
    <div className="bell-wrap" ref={bellRef}>
      <button className="bell-btn" onClick={() => setOpen(o => !o)}>
        🔔
        {invites.length > 0 && (
          <span className="bell-badge">{invites.length}</span>
        )}
      </button>

      {open && (
        <div className="bell-dropdown">
          <div className="bell-header">Notifications</div>
          {invites.length === 0 ? (
            <div className="bell-empty">No new notifications</div>
          ) : (
            invites.map(invite => (
              <div key={invite.id} className="bell-invite">
                <div className="bell-invite-text">
                  <strong>{invite.from_name}</strong> wants to watch
                  <br />
                  <em>"{invite.movie_title}"</em> with you
                </div>
                <div className="bell-invite-actions">
                  <button className="bell-accept" onClick={() => respond(invite.id, 'accepted', invite)}>
                    Accept
                  </button>
                  <button className="bell-decline" onClick={() => respond(invite.id, 'declined', invite)}>
                    Decline
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}