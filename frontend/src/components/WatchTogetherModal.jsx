import { useState } from 'react'
import { useAuth } from '../context/AuthContext'
import './WatchTogetherModal.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

export default function WatchTogetherModal({ movie, onClose, onPartyStart }) {
  const { user, profile } = useAuth()
  const [email, setEmail]       = useState('')
  const [status, setStatus]     = useState('idle')
  const [message, setMessage]   = useState('')
  const [roomId, setRoomId]     = useState(null)  // store real room_id

  const senderName = profile?.name || user?.name || 'Someone'

  const handleInvite = async () => {
    if (!email.trim()) return
    setStatus('checking')
    setMessage('')

    try {
      if (email.trim().toLowerCase() === user?.email?.toLowerCase()) {
        setStatus('error')
        setMessage("You can't invite yourself.")
        return
      }

      setStatus('sending')

      const inviteRes  = await fetch(`${API_BASE}/invite`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          from_email:  user?.email,
          from_name:   senderName,
          to_email:    email.trim(),
          movie_title: movie.title,
          movie_id:    movie.item_id,
        }),
      })
      const inviteData = await inviteRes.json()

      if (!inviteRes.ok) {
        setStatus('error')
        setMessage(inviteData.detail || 'Failed to send invite.')
        return
      }

      // Store the real room_id
      setRoomId(inviteData.room_id)
      setStatus('sent')
      setMessage(`Invite sent to ${checkData.name}! You can start watching now — they'll join when they accept.`)

    } catch (e) {
      setStatus('error')
      setMessage('Could not connect to server. Check your connection.')
    }
  }

  return (
    <div className="wt-overlay" onClick={onClose}>
      <div className="wt-modal" onClick={e => e.stopPropagation()}>
        <button className="wt-close" onClick={onClose}>✕</button>

        <div className="wt-title">Watch Together</div>
        <div className="wt-movie">🎬 {movie.title}</div>

        {status !== 'sent' ? (
          <>
            <p className="wt-desc">
              Enter your friend's STREAMORA email. They'll get a notification to join.
            </p>
            <input
              className="wt-input"
              type="email"
              placeholder="friend@email.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleInvite()}
              disabled={status === 'checking' || status === 'sending'}
            />
            {message && (
              <p className={`wt-message ${status === 'error' ? 'error' : ''}`}>{message}</p>
            )}
            <button
              className="wt-send-btn"
              onClick={handleInvite}
              disabled={status === 'checking' || status === 'sending' || !email.trim()}
            >
              {status === 'checking' ? 'Checking...' : status === 'sending' ? 'Sending...' : 'Send Invite'}
            </button>
          </>
        ) : (
          <div className="wt-waiting">
            <div className="wt-spinner">🎬</div>
            <p className="wt-message">{message}</p>
            <p className="wt-hint">
              Your friend will see a 🔔 notification. Once they accept, they'll join you in the same room.
            </p>
            <button
              className="wt-send-btn"
              onClick={() => onPartyStart?.({
                roomId:     roomId,
                movieId:    movie.item_id,
                movieTitle: movie.title,
              })}
            >
              Start Watching Now
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
