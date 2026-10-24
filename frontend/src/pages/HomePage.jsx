import { useState, useEffect, useCallback, useRef } from 'react'
import { useAuth } from '../context/AuthContext'
import { getRecommendations, getTMDBNowPlaying, getTMDBPopular, getTMDBData, sendFeedback } from '../api/client'
import MovieRow from '../components/MovieRow'
import MovieModal from '../components/MovieModal'
import HeroSection from '../components/HeroSection'
import './HomePage.css'

export default function HomePage({ onWatchTogether }) {
  const { profile, watchHistory, continueWatching, watchedMovies, addToContinueWatching } = useAuth()
  const profileId = profile?.id

  const [recommendations, setRecommendations] = useState([])
  const [modelVariant, setModelVariant]       = useState('bert4rec')
  const [nowPlaying, setNowPlaying]           = useState([])
  const [popular, setPopular]                 = useState([])
  const [selectedMovie, setSelectedMovie]     = useState(null)
  const [selectedTmdb, setSelectedTmdb]       = useState(null)
  const [loading, setLoading]                 = useState(true)
  const [refreshCount, setRefreshCount]       = useState(0)
  const [interactedIds, setInteractedIds]     = useState(new Set())

  const [heroItems, setHeroItems] = useState([])
  const [heroIndex, setHeroIndex] = useState(0)
  const autoAdvanceRef = useRef(null)
  const popularRef     = useRef([])

  function tmdbToMovie(t) {
    return {
      item_id: `tmdb_${t.id}`,
      item_idx: -1,
      title: t.title,
      release_year: t.release_date?.split('-')[0],
      genres: [],
      log_popularity: Math.log(t.popularity || 1),
    }
  }

  function tmdbToData(t) {
    return {
      tmdbId: t.id,
      backdropUrl: t.backdrop_path ? `https://image.tmdb.org/t/p/original${t.backdrop_path}` : null,
      posterUrl:   t.poster_path   ? `https://image.tmdb.org/t/p/w500${t.poster_path}`        : null,
      overview: t.overview,
      rating:   t.vote_average?.toFixed(1),
    }
  }

  const startAutoAdvance = useCallback(() => {
    if (autoAdvanceRef.current) clearInterval(autoAdvanceRef.current)
    autoAdvanceRef.current = setInterval(() => {
      setHeroIndex(i => (i + 1) % 5)
    }, 6000)
  }, [])

  useEffect(() => {
    if (heroItems.length === 0) return
    setHeroIndex(Math.floor(Math.random() * Math.min(heroItems.length, 5)))
    startAutoAdvance()
    return () => clearInterval(autoAdvanceRef.current)
  }, [heroItems, startAutoAdvance])

  const goToHero = useCallback((i) => { setHeroIndex(i); startAutoAdvance() }, [startAutoAdvance])
  const heroPrev = useCallback(() => { setHeroIndex(i => (i - 1 + Math.min(heroItems.length, 5)) % Math.min(heroItems.length, 5)); startAutoAdvance() }, [heroItems.length, startAutoAdvance])
  const heroNext = useCallback(() => { setHeroIndex(i => (i + 1) % Math.min(heroItems.length, 5)); startAutoAdvance() }, [heroItems.length, startAutoAdvance])

  // Load TMDB once on mount
  useEffect(() => {
    const loadTMDB = async () => {
      try {
        const [playingRes, popularRes] = await Promise.all([getTMDBNowPlaying(), getTMDBPopular()])
        setNowPlaying(playingRes.map(tmdbToMovie))
        setPopular(popularRes.map(tmdbToMovie))
        popularRef.current = popularRes
        const heroFallback = popularRes.filter(m => m.backdrop_path).slice(0, 5)
          .map(m => ({ movie: tmdbToMovie(m), tmdbData: tmdbToData(m) }))
        setHeroItems(heroFallback)
      } catch (e) { console.error('TMDB load failed:', e) }
      setLoading(false)
    }
    loadTMDB()
  }, [])

  // Load recommendations when history or refreshCount changes
  useEffect(() => {
    const loadRecs = async () => {
      const storedHistory = localStorage.getItem('nf_history')
      const freshHistory  = storedHistory ? JSON.parse(storedHistory) : []
      if (freshHistory.length === 0) return
      try {
        const recRes = await getRecommendations(freshHistory, profileId, 20)
        const recs   = recRes.recommendations || []
        setRecommendations(recs)
        setModelVariant(recRes.model_variant)
        // Reset interacted ids when recommendations refresh
        setInteractedIds(new Set())
        if (recs.length > 0) {
          const heroRecs = await Promise.all(
            recs.slice(0, 5).map(async (movie) => {
              const tmdbData = await getTMDBData(movie.title, movie.release_year)
              return tmdbData?.backdropUrl ? { movie, tmdbData } : null
            })
          )
          const valid = heroRecs.filter(Boolean)
          if (valid.length >= 2) setHeroItems(valid)
        }
      } catch (e) { console.error('Recommendations failed:', e) }
    }
    loadRecs()
  }, [profileId, refreshCount, watchHistory.length])

  const handleMovieClick = useCallback((movie, tmdbData) => {
    setSelectedMovie(movie)
    setSelectedTmdb(tmdbData || null)
    // Track interacted movies to remove from recommendations
    if (movie?.item_id) {
      setInteractedIds(prev => new Set([...prev, movie.item_id]))
    }
  }, [])

  const handleFeedback = useCallback(async (movieId, signal, variant) => {
    try {
      await sendFeedback(profileId, movieId, signal, variant || modelVariant)
      if (signal === -1) {
        // Remove thumbs down movie from recommendations immediately
        setRecommendations(prev => prev.filter(m => m.item_id !== movieId))
      } else if (signal === 1) {
        // Thumbs up — trigger recommendations refresh
        setRefreshCount(c => c + 1)
      }
    } catch (e) { console.error('Feedback error:', e) }
  }, [profileId, modelVariant])

  const continueWatchingMovies = continueWatching.map(cw => cw.movie)
  const continueWatchingIds = new Set(continueWatching.map(cw => cw.movie?.item_id).filter(Boolean))
  const unwatchedRecs = watchHistory.length >= 6
    ? recommendations.filter(m => !interactedIds.has(m.item_id) && !continueWatchingIds.has(m.item_id))
    : recommendations.filter(m => !continueWatchingIds.has(m.item_id))
  const currentHero = heroItems[heroIndex] || null

  return (
    <div className="home-page">
      {currentHero && (
        <div className="hero-carousel">
          <HeroSection
            movie={currentHero.movie}
            tmdbData={currentHero.tmdbData}
            onPlay={() => { addToContinueWatching(currentHero.movie); handleMovieClick(currentHero.movie, currentHero.tmdbData) }}
            onMoreInfo={() => handleMovieClick(currentHero.movie, currentHero.tmdbData)}
          />
          {heroItems.length > 1 && (
            <>
              <button className="hero-arrow hero-arrow-left" onClick={heroPrev} aria-label="Previous">‹</button>
              <button className="hero-arrow hero-arrow-right" onClick={heroNext} aria-label="Next">›</button>
            </>
          )}
          {heroItems.length > 1 && (
            <div className="hero-dots">
              {heroItems.slice(0, 5).map((_, i) => (
                <button key={i} className={`hero-dot ${i === heroIndex ? 'active' : ''}`}
                  onClick={() => goToHero(i)} aria-label={`Go to slide ${i + 1}`} />
              ))}
            </div>
          )}
        </div>
      )}

      <div className={`home-rows ${loading ? 'loading' : ''}`}>
        {continueWatchingMovies.length > 0 && (
          <MovieRow title="Continue Watching" movies={continueWatchingMovies}
            onMovieClick={handleMovieClick} showFeedback modelVariant={modelVariant} onFeedback={handleFeedback} />
        )}
        {unwatchedRecs.length > 0 && (
          <MovieRow title="Recommended For You" movies={unwatchedRecs}
            onMovieClick={handleMovieClick} showFeedback modelVariant={modelVariant} onFeedback={handleFeedback} />
        )}
        {watchHistory.length < 3 && (
          <MovieRow title="Popular on STREAMORA" movies={popular} onMovieClick={handleMovieClick} />
        )}
        <MovieRow title="New Releases"  movies={nowPlaying}           onMovieClick={handleMovieClick} />
        <MovieRow title="Trending Now"  movies={popular.slice(10,30)} onMovieClick={handleMovieClick} />
      </div>

      {selectedMovie && (
        <MovieModal
          movie={selectedMovie}
          tmdbData={selectedTmdb}
          modelVariant={modelVariant}
          onClose={() => { setSelectedMovie(null); setSelectedTmdb(null) }}
          onWatchTogether={(party) => { setSelectedMovie(null); onWatchTogether?.(party) }}
          onFeedback={handleFeedback}
        />
      )}
    </div>
  )
}