import { useState, useEffect, useRef, useCallback } from 'react'
import { useAuth } from '../context/AuthContext'
import { API_BASE, getToken, getTrailerKey, parseTMDBItemId } from '../api/client'
import './WatchPartyPage.css'

const WS_BASE  = API_BASE.replace('http', 'ws')

export default function WatchPartyPage({ roomId, movieId, movieTitle, onLeave }) {
  const { user, logout } = useAuth()
  // The server sets each chat message's sender to the account name
  const userName = user?.name

  const [messages, setMessages]     = useState([])
  const [input, setInput]           = useState('')
  const [connected, setConnected]   = useState(false)
  const [error, setError]           = useState('')
  const [participants, setParticipants] = useState(1)
  const wsRef    = useRef(null)
  const chatRef  = useRef(null)

  const [trailerKey, setTrailerKey] = useState(null)

  // Fetch trailer through the backend TMDB proxy
  useEffect(() => {
    const parsed = parseTMDBItemId(movieId)
    if (!parsed) return
    getTrailerKey(parsed.tmdbId, parsed.mediaType).then(key => { if (key) setTrailerKey(key) })
  }, [movieId])

  // Connect WebSocket
  useEffect(() => {
    const ws = new WebSocket(`${WS_BASE}/ws/room/${roomId}`)
    wsRef.current = ws

    ws.onopen = () => {
      // Browsers cannot send an Authorization header on a WebSocket, so the
      // access token is sent as the first message instead.
      ws.send(JSON.stringify({ type: 'auth', token: getToken() }))
      setConnected(true)
      setMessages(prev => [...prev, {
        type: 'system',
        text: 'Connected to watch party room',
        timestamp: new Date().toISOString(),
      }])
    }

    ws.onmessage = (e) => {
      let msg
      try { msg = JSON.parse(e.data) } catch { return }
      if (msg.type === 'error') return
      setMessages(prev => [...prev, msg])
      if (typeof msg.participants === 'number') setParticipants(msg.participants)
    }

    ws.onclose = (e) => {
      setConnected(false)
      if (e.code === 4401) logout()
      else if (e.code === 4403) setError('You are not a participant in this watch party.')
    }

    return () => ws.close()
  }, [roomId, logout])

  // Auto-scroll chat
  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight
    }
  }, [messages])

  const sendMessage = useCallback(() => {
    if (!input.trim() || !wsRef.current) return
    wsRef.current.send(JSON.stringify({ type: 'chat', text: input.trim() }))
    setInput('')
    // Don't add locally — server broadcasts back to all including sender
  }, [input])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  return (
    <div className="watch-party-page">
      {/* Header */}
      <div className="watch-party-header">
        <div className="watch-party-title">
          <span className="wp-logo">STREAMORA</span>
          <span className="wp-movie-name">🎬 {movieTitle}</span>
          <span className="wp-participants">👥 {participants} watching</span>
          <span className={`wp-status ${connected ? 'connected' : 'disconnected'}`}>
            {error || (connected ? '● Live' : '● Connecting...')}
          </span>
        </div>
        <button className="wp-leave-btn" onClick={onLeave}>Leave Party</button>
      </div>

      <div className="watch-party-body">
        {/* Video */}
        <div className="watch-party-video">
          {trailerKey ? (
            <iframe
              src={`https://www.youtube.com/embed/${trailerKey}?autoplay=1&rel=0`}
              title={movieTitle}
              allowFullScreen
              allow="autoplay; encrypted-media"
              className="wp-iframe"
            />
          ) : (
            <div className="wp-no-trailer">
              <div style={{ fontSize: '64px' }}>🎬</div>
              <p>{movieTitle}</p>
              <p style={{ color: '#666', fontSize: '14px' }}>Trailer not available</p>
            </div>
          )}
        </div>

        {/* Chat */}
        <div className="watch-party-chat">
          <div className="chat-header">Watch Party Chat</div>

          <div className="chat-messages" ref={chatRef}>
            {messages.map((msg, i) => (
              <div key={i} className={`chat-msg ${msg.type === 'system' ? 'system' : msg.self ? 'self' : 'other'}`}>
                {msg.type === 'system' ? (
                  <span className="system-text">{msg.text}</span>
                ) : (
                  <>
                    <div className="msg-sender" style={{ color: msg.sender === userName ? '#e50914' : '#aaa' }}>
                      {msg.sender === userName ? 'You' : msg.sender}
                    </div>
                    <div className="msg-bubble">{msg.text}</div>
                    <div className="msg-time">
                      {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>

          <div className="chat-input-row">
            <input
              className="chat-input"
              type="text"
              placeholder="Say something..."
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              maxLength={300}
            />
            <button className="chat-send-btn" onClick={sendMessage}>Send</button>
          </div>
        </div>
      </div>
    </div>
  )
}
