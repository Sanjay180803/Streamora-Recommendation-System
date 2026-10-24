import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import { apiFetch, getToken, setToken } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  // A stored user without a token predates token auth and must log in again
  const [user, setUser]       = useState(() => { try { return getToken() ? JSON.parse(localStorage.getItem('nf_user')) : null } catch { return null } })
  const [profile, setProfile] = useState(() => { try { return JSON.parse(localStorage.getItem('nf_profile')) } catch { return null } })
  const [profiles, setProfiles] = useState(() => { try { return JSON.parse(localStorage.getItem('nf_profiles')) || [] } catch { return [] } })

  const [watchHistory, setWatchHistory]         = useState([])
  const [continueWatching, setContinueWatching] = useState([])
  const [watchedMovies, setWatchedMovies]       = useState(new Set())

  const profileRef = useRef(profile)
  const userRef    = useRef(user)
  useEffect(() => { profileRef.current = profile }, [profile])
  useEffect(() => { userRef.current = user }, [user])

  useEffect(() => {
    if (user?.email && profiles.length === 0) {
      apiFetch('/profiles')
        .then(r => r.json())
        .then(data => {
          if (data.profiles?.length > 0) {
            setProfiles(data.profiles)
            localStorage.setItem('nf_profiles', JSON.stringify(data.profiles))
          }
        })
        .catch(() => {})
    }
  }, [user?.email])

  useEffect(() => {
    if (!user?.email || !profile?.id) return
    const load = async () => {
      try {
        const [histRes, cwRes] = await Promise.all([
          apiFetch(`/history/${profile.id}`),
          apiFetch(`/continue-watching/${profile.id}`),
        ])
        if (!histRes.ok || !cwRes.ok) throw new Error('Failed to load profile data')
        const histData = await histRes.json()
        const cwData   = await cwRes.json()

        const hist = histData.history || []
        setWatchHistory(hist)
        setWatchedMovies(new Set(hist.map(h => h.title || h)))
        localStorage.setItem('nf_history', JSON.stringify(hist))
        localStorage.setItem(`nf_history_${profile.id}`, JSON.stringify(hist))

        const cw = cwData.items || []
        setContinueWatching(cw)
        localStorage.setItem(`nf_continue_${profile.id}`, JSON.stringify(cw))
      } catch {
        const hist = JSON.parse(localStorage.getItem(`nf_history_${profile.id}`) || '[]')
        setWatchHistory(hist)
        setWatchedMovies(new Set(hist.map(h => h.title || h)))
        const cw = JSON.parse(localStorage.getItem(`nf_continue_${profile.id}`) || '[]')
        setContinueWatching(cw)
      }
    }
    load()
  }, [user?.email, profile?.id])

  const saveHistoryToBackend = useCallback(async (history) => {
    const u = userRef.current
    const p = profileRef.current
    if (!u?.email || !p?.id) return
    try {
      await apiFetch('/history/save', {
        method: 'POST',
        body: { profile_id: p.id, history },
      })
    } catch { /* best effort: the local copy stays in localStorage */ }
  }, [])

  const saveCWToBackend = useCallback(async (items) => {
    const u = userRef.current
    const p = profileRef.current
    if (!u?.email || !p?.id) return
    try {
      await apiFetch('/continue-watching/save', {
        method: 'POST',
        body: { profile_id: p.id, items },
      })
    } catch { /* best effort: the local copy stays in localStorage */ }
  }, [])

  const login = useCallback((userData) => {
    if (userData.token) setToken(userData.token)
    const userToStore = { email: userData.email, name: userData.name }
    setUser(userToStore)
    userRef.current = userToStore
    localStorage.setItem('nf_user', JSON.stringify(userToStore))
    // Always update profiles regardless of length
    if (userData.profiles !== undefined) {
      setProfiles(userData.profiles)
      localStorage.setItem('nf_profiles', JSON.stringify(userData.profiles))
    }
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setUser(null); setProfile(null); setProfiles([])
    setWatchHistory([]); setWatchedMovies(new Set())
    setContinueWatching([])
    userRef.current = null
    profileRef.current = null
    localStorage.removeItem('nf_user')
    localStorage.removeItem('nf_profile')
    localStorage.removeItem('nf_profiles')
    localStorage.removeItem('nf_history')
  }, [])

  // client.js fires this when the backend rejects the stored token
  useEffect(() => {
    window.addEventListener('auth:expired', logout)
    return () => window.removeEventListener('auth:expired', logout)
  }, [logout])

  const selectProfile = useCallback((prof) => {
    setProfile(prof)
    profileRef.current = prof
    setWatchHistory([]); setWatchedMovies(new Set())
    setContinueWatching([])
    if (prof) localStorage.setItem('nf_profile', JSON.stringify(prof))
    else localStorage.removeItem('nf_profile')
  }, [])

  const addToHistory = useCallback((movie) => {
    const p = profileRef.current
    setWatchHistory(prev => {
      const filtered = prev.filter(m => (m.title || m) !== (movie.title || movie))
      const updated  = [movie, ...filtered].slice(0, 50)
      localStorage.setItem('nf_history', JSON.stringify(updated))
      if (p?.id) localStorage.setItem(`nf_history_${p.id}`, JSON.stringify(updated))
      setWatchedMovies(new Set(updated.map(h => h.title || h)))
      saveHistoryToBackend(updated)
      return updated
    })
  }, [saveHistoryToBackend])

  const addToContinueWatching = useCallback((movie) => {
    const p = profileRef.current
    addToHistory(movie)
    setContinueWatching(prev => {
      const filtered = prev.filter(cw => (cw.movie?.title || cw.movie) !== (movie.title || movie))
      const updated  = [{ movie, progress: 0.1 }, ...filtered].slice(0, 20)
      if (p?.id) localStorage.setItem(`nf_continue_${p.id}`, JSON.stringify(updated))
      saveCWToBackend(updated)
      return updated
    })
  }, [addToHistory, saveCWToBackend])

  const updateProgress = useCallback((movie, progress) => {
    if (progress < 0.9) addToContinueWatching(movie)
  }, [addToContinueWatching])

  return (
    <AuthContext.Provider value={{
      user, profile, profiles,
      watchHistory, continueWatching, watchedMovies,
      login, logout, selectProfile,
      addToHistory, updateProgress, addToContinueWatching,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components -- the hook belongs with its context
export const useAuth = () => useContext(AuthContext)