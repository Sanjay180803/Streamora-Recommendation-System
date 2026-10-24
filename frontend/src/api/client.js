import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

// ── FastAPI client ─────────────────────────────────────────────────────────
const api = axios.create({ baseURL: BASE_URL, timeout: 15000 })

// ── TMDB client ────────────────────────────────────────────────────────────
// Requests go through the backend proxy, which holds the TMDB token.
const tmdb = axios.create({ baseURL: `${BASE_URL}/tmdb`, timeout: 10000 })

// ── FastAPI calls ──────────────────────────────────────────────────────────

export async function getRecommendations(watchHistory, sessionId, topK = 20) {
  const items = watchHistory.map(item =>
    typeof item === 'string'
      ? { title: item, genres: [], release_year: null }
      : { title: item.title, genres: item.genres || [], release_year: item.release_year || null }
  )
  const res = await api.post('/recommend', { watch_history: items, session_id: sessionId, top_k: topK })
  return res.data
}

export async function sendFeedback(sessionId, movieId, signal, modelVariant) {
  const res = await api.post('/feedback', { session_id: sessionId, movie_id: movieId, signal, model_variant: modelVariant })
  return res.data
}

export async function getGenres() {
  const res = await api.get('/genres')
  return res.data.genres
}

export async function checkHealth() {
  const res = await api.get('/health')
  return res.data
}

// ── TMDB cache ─────────────────────────────────────────────────────────────
const tmdbCache = new Map()

export async function getTMDBData(title, year) {
  const cacheKey = `${title}-${year}`
  if (tmdbCache.has(cacheKey)) return tmdbCache.get(cacheKey)
  try {
    const res = await tmdb.get('/search/movie', { params: { query: title, year, language: 'en-US', page: 1 } })
    const movie = res.data.results?.[0]
    if (!movie) { tmdbCache.set(cacheKey, null); return null }
    const data = {
      tmdbId: movie.id,
      posterUrl: movie.poster_path ? `https://image.tmdb.org/t/p/w500${movie.poster_path}` : null,
      backdropUrl: movie.backdrop_path ? `https://image.tmdb.org/t/p/original${movie.backdrop_path}` : null,
      overview: movie.overview,
      rating: movie.vote_average?.toFixed(1),
      popularity: movie.popularity,
    }
    tmdbCache.set(cacheKey, data)
    return data
  } catch { tmdbCache.set(cacheKey, null); return null }
}

export async function getTrailerKey(tmdbId, mediaType = 'movie') {
  if (!tmdbId) return null
  try {
    const res = await tmdb.get(`/${mediaType}/${tmdbId}/videos`, { params: { language: 'en-US' } })
    const videos = res.data.results || []
    const trailer = videos.find(v => v.type === 'Trailer' && v.site === 'YouTube') || videos.find(v => v.site === 'YouTube')
    return trailer ? trailer.key : null
  } catch { return null }
}

export async function searchTMDB(mediaType, query) {
  try {
    const res = await tmdb.get(`/search/${mediaType}`, { params: { query, language: 'en-US', page: 1 } })
    return res.data.results || []
  } catch { return [] }
}

// Parses the item ids produced by movieToCard / tvToMovie ("tmdb_123", "tmdb_tv_123")
export function parseTMDBItemId(itemId) {
  const match = /^tmdb_(tv_)?(\d+)$/.exec(itemId || '')
  if (!match) return null
  return { mediaType: match[1] ? 'tv' : 'movie', tmdbId: match[2] }
}

// ── TMDB Movies ────────────────────────────────────────────────────────────

export async function getTMDBPopular() {
  try {
    const res = await tmdb.get('/movie/popular', { params: { language: 'en-US', page: 1 } })
    return res.data.results || []
  } catch { return [] }
}

export async function getTMDBNowPlaying() {
  try {
    const res = await tmdb.get('/movie/now_playing', { params: { language: 'en-US', page: 1 } })
    return res.data.results || []
  } catch { return [] }
}

export async function getTMDBTopRatedMovies() {
  try {
    const res = await tmdb.get('/movie/top_rated', { params: { language: 'en-US', page: 1 } })
    return res.data.results || []
  } catch { return [] }
}

// ── TMDB TV Shows ──────────────────────────────────────────────────────────

export async function getTMDBPopularTV() {
  try {
    const res = await tmdb.get('/tv/popular', { params: { language: 'en-US', page: 1 } })
    return res.data.results || []
  } catch { return [] }
}

export async function getTMDBOnAirTV() {
  try {
    const res = await tmdb.get('/tv/on_the_air', { params: { language: 'en-US', page: 1 } })
    return res.data.results || []
  } catch { return [] }
}

export async function getTMDBTopRatedTV() {
  try {
    const res = await tmdb.get('/tv/top_rated', { params: { language: 'en-US', page: 1 } })
    return res.data.results || []
  } catch { return [] }
}

export async function getTMDBTrendingAll() {
  try {
    const res = await tmdb.get('/trending/all/week', { params: { language: 'en-US' } })
    return res.data.results || []
  } catch { return [] }
}

// ── Helpers: convert TMDB TV to movie card format ──────────────────────────

export function tvToMovie(t) {
  return {
    item_id: `tmdb_tv_${t.id}`,
    item_idx: -1,
    title: t.name || t.original_name,
    release_year: t.first_air_date?.split('-')[0],
    genres: [],
    log_popularity: Math.log(t.popularity || 1),
    media_type: 'tv',
    tmdb_id: t.id,
  }
}

export function tvToData(t) {
  return {
    tmdbId: t.id,
    mediaType: 'tv',
    posterUrl: t.poster_path ? `https://image.tmdb.org/t/p/w500${t.poster_path}` : null,
    backdropUrl: t.backdrop_path ? `https://image.tmdb.org/t/p/original${t.backdrop_path}` : null,
    overview: t.overview,
    rating: t.vote_average?.toFixed(1),
  }
}

export function movieToCard(m) {
  return {
    item_id: `tmdb_${m.id}`,
    item_idx: -1,
    title: m.title,
    release_year: m.release_date?.split('-')[0],
    genres: [],
    log_popularity: Math.log(m.popularity || 1),
    media_type: 'movie',
    tmdb_id: m.id,
  }
}

export function movieToData(m) {
  return {
    tmdbId: m.id,
    mediaType: 'movie',
    posterUrl: m.poster_path ? `https://image.tmdb.org/t/p/w500${m.poster_path}` : null,
    backdropUrl: m.backdrop_path ? `https://image.tmdb.org/t/p/original${m.backdrop_path}` : null,
    overview: m.overview,
    rating: m.vote_average?.toFixed(1),
  }
}
