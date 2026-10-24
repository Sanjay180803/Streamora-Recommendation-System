import { useState, useEffect, useRef, useCallback } from 'react'
import { useAuth } from '../context/AuthContext'
import { getTrailerKey, parseTMDBItemId } from '../api/client'
import './WatchPartyPage.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
const WS_BASE  = API_BASE.replace('http', 'ws')

export default function WatchPartyPage({ roomId, movieId, movieTitle, onLeave }) {
  const { user, profile } = useAuth()
  const userName = user?.name || profile?.name || 'Guest'

  const [messages, setMessages]     = useState([])
  const [input, setInput]           = useState('')
  const [connected, setConnected]   = useState(false)
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
    const ws = new WebSocket(`${WS_BASE}/ws/room/${roomId}?name=${encodeURIComponent(userName)}`)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      setMessages(prev => [...prev, {
        type: 'system',
        text: 'Connected to watch party room',
        timestamp: new Date().toISOString(),
      }])
    }

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      setMessages(prev => [...prev, msg])
      if (msg.type === 'system') {
        setParticipants(prev => msg.text.includes('joined') ? prev + 1 : Math.max(1, prev - 1))
      }
    }

    ws.onclose = () => setConnected(false)

    return () => ws.close()
  }, [roomId, userName])

  // Auto-scroll chat
  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight
    }
  }, [messages])

  const sendMessage = useCallback(() => {
    if (!input.trim() || !wsRef.current) return
    const msg = { type: 'chat', text: input.trim(), sender: userName }
    wsRef.current.send(JSON.stringify(msg))
    setInput('')
    // Don't add locally — server broadcasts back to all including sender
  }, [input, userName])

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
            {connected ? '● Live' : '● Connecting...'}
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
