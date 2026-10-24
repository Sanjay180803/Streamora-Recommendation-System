import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { apiFetch } from '../api/client'
import './ProfilePage.css'


const AVATAR_OPTIONS = [
  { icon: '🎬', color: '#e50914' },
  { icon: '🎭', color: '#0080ff' },
  { icon: '⭐', color: '#ffb800' },
  { icon: '🎪', color: '#00b894' },
  { icon: '🚀', color: '#6c5ce7' },
  { icon: '🎵', color: '#fd79a8' },
  { icon: '🏆', color: '#e17055' },
  { icon: '🌙', color: '#2d3436' },
  { icon: '🎮', color: '#00cec9' },
  { icon: '🦁', color: '#fdcb6e' },
  { icon: '🐉', color: '#d63031' },
  { icon: '🌺', color: '#e84393' },
]

export default function ProfilePage() {
  const { profiles, selectProfile, login, user, logout } = useAuth()
  const navigate = useNavigate()
  const [showAdd, setShowAdd]               = useState(false)
  const [managing, setManaging]             = useState(false)
  const [newName, setNewName]               = useState('')
  const [selectedAvatar, setSelectedAvatar] = useState(AVATAR_OPTIONS[0])
  const [saving, setSaving]                 = useState(false)
  const [error, setError]                   = useState('')

  const handleSelect = (profile) => {
    if (managing) return
    selectProfile(profile)
    navigate('/')
  }

  const handleAddProfile = async () => {
    if (!newName.trim()) { setError('Please enter a name.'); return }
    if (profiles.some(p => p.name.toLowerCase() === newName.trim().toLowerCase())) {
      setError('A profile with this name already exists.')
      return
    }
    setSaving(true)
    setError('')
    try {
      const res = await apiFetch('/profiles/create', {
        method: 'POST',
        body: {
          name: newName.trim(),
          color: selectedAvatar.color,
          icon: selectedAvatar.icon,
        },
      })
      const data = await res.json()
      if (!res.ok) { setError(data.detail || 'Failed to create profile.'); setSaving(false); return }
      login({ ...user, profiles: [...profiles, data] })
      setShowAdd(false)
      setNewName('')
      setSelectedAvatar(AVATAR_OPTIONS[0])
    } catch { setError('Could not connect to server.') }
    setSaving(false)
  }

  const handleDeleteProfile = async (e, profileId) => {
    e.stopPropagation()
    if (!window.confirm('Delete this profile? All its data will be lost.')) return
    try {
      const res = await apiFetch('/profiles/delete', {
        method: 'POST',
        body: { profile_id: profileId },
      })
      if (res.ok) {
        const remaining = profiles.filter(p => p.id !== profileId)
        login({ ...user, profiles: remaining })
        // If last profile was deleted, exit managing mode
        if (remaining.length === 0) setManaging(false)
      }
    } catch { alert('Failed to delete profile.') }
  }

  const handleRenameProfile = async (e, profileId, currentName) => {
    e.stopPropagation()
    const newNameVal = window.prompt('Enter new name:', currentName)
    if (!newNameVal || newNameVal.trim() === currentName) return
    if (profiles.some(p => p.name.toLowerCase() === newNameVal.trim().toLowerCase() && p.id !== profileId)) {
      alert('A profile with this name already exists.'); return
    }
    try {
      const res = await apiFetch('/profiles/rename', {
        method: 'POST',
        body: { profile_id: profileId, new_name: newNameVal.trim() },
      })
      if (res.ok) login({ ...user, profiles: profiles.map(p => p.id === profileId ? { ...p, name: newNameVal.trim() } : p) })
    } catch { alert('Failed to rename profile.') }
  }

  // ── Add Profile form ────────────────────────────────────────────────────
  if (showAdd) {
    return (
      <div className="profile-page">
        <div className="profile-logo">STREAMORA</div>
        <div className="profile-content">
          <h1 className="profile-heading">Create Profile</h1>
          <div className="add-profile-form">
            <input className="add-profile-input" type="text" placeholder="Profile name"
              value={newName} onChange={e => setNewName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleAddProfile()} autoFocus />
            <p className="avatar-label">Choose an avatar</p>
            <div className="avatar-grid">
              {AVATAR_OPTIONS.map((av, i) => (
                <div key={i} className={`avatar-option ${selectedAvatar === av ? 'selected' : ''}`}
                  style={{ background: av.color }} onClick={() => setSelectedAvatar(av)}>
                  <span style={{ fontSize: '28px' }}>{av.icon}</span>
                </div>
              ))}
            </div>
            {error && <p className="add-profile-error">{error}</p>}
            <div className="add-profile-actions">
              <button className="add-profile-save" onClick={handleAddProfile} disabled={saving}>
                {saving ? 'Saving...' : 'Save Profile'}
              </button>
              <button className="add-profile-cancel" onClick={() => { setShowAdd(false); setError('') }}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // ── Who's Watching page ─────────────────────────────────────────────────
  return (
    <div className="profile-page">
      <div className="profile-logo">STREAMORA</div>
      <div className="profile-content">
        <h1 className="profile-heading">
          {managing ? 'Manage Profiles' : "Who's watching?"}
        </h1>

        <div className="profile-grid">
          {profiles.map(p => (
            <div key={p.id} className={`profile-item ${managing ? 'managing' : ''}`}
              onClick={() => handleSelect(p)} role="button" tabIndex={0}
              onKeyDown={e => e.key === 'Enter' && handleSelect(p)}>
              <div className="profile-icon-wrap" style={{ background: p.color }}>
                <span className="profile-icon">{p.icon || '🎬'}</span>
                {managing && (
                  <div className="profile-edit-overlay">
                    <button className="profile-action-btn rename-btn"
                      onClick={e => handleRenameProfile(e, p.id, p.name)} title="Rename">✏️</button>
                    <button className="profile-action-btn delete-btn"
                      onClick={e => handleDeleteProfile(e, p.id)} title="Delete">🗑️</button>
                  </div>
                )}
              </div>
              <span className="profile-name">{p.name}</span>
            </div>
          ))}

          {/* Add Profile card — always show if under limit */}
          {profiles.length < 6 && (
            <div className="profile-item add-profile-card"
              onClick={() => setShowAdd(true)} role="button" tabIndex={0}>
              <div className="profile-icon-wrap profile-add">
                <span className="profile-add-icon">+</span>
                <span className="profile-add-label">Add Profile</span>
              </div>
            </div>
          )}
        </div>

        {/* Only show footer buttons if there are profiles */}
        {profiles.length > 0 && (
          <div className="profile-footer-btns">
            <button className="profile-manage-btn" onClick={() => setManaging(m => !m)}>
              {managing ? 'Done' : 'Manage Profiles'}
            </button>
            <button className="profile-signout-btn" onClick={() => { logout(); navigate('/') }}>
              Sign Out
            </button>
          </div>
        )}

        {/* Show sign out only when no profiles remain */}
        {profiles.length === 0 && (
          <div className="profile-footer-btns">
            <button className="profile-signout-btn" onClick={() => { logout(); navigate('/') }}>
              Sign Out
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
