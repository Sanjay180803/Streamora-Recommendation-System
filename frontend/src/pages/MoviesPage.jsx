import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../context/AuthContext'
import { getRecommendations, getTMDBPopular, getTMDBNowPlaying, getTMDBTopRatedMovies, movieToCard, movieToData } from '../api/client'
import MovieRow from '../components/MovieRow'
import MovieModal from '../components/MovieModal'
import './HomePage.css'

export default function MoviesPage() {
  const { profile, watchHistory } = useAuth()
  const profileId = profile?.id
  const [recs, setRecs]           = useState([])
  const [popular, setPopular]     = useState([])
  const [nowPlaying, setNowPlaying] = useState([])
  const [topRated, setTopRated]   = useState([])
  const [modelVariant, setModelVariant] = useState('bert4rec')
  const [selectedMovie, setSelectedMovie] = useState(null)
  const [selectedTmdb, setSelectedTmdb]   = useState(null)
  const [loading, setLoading]     = useState(true)

  useEffect(() => {
    const load = async () => {
      const [pop, now, top] = await Promise.all([
        getTMDBPopular(),
        getTMDBNowPlaying(),
        getTMDBTopRatedMovies(),
      ])
      setPopular(pop.map(movieToCard))
      setNowPlaying(now.map(movieToCard))
      setTopRated(top.map(movieToCard))

      if (watchHistory.length >= 1) {
        try {
          const storedHistory = localStorage.getItem('nf_history')
          const freshHistory = storedHistory ? JSON.parse(storedHistory) : []
          const recRes = await getRecommendations(freshHistory, profileId, 20)
          setRecs(recRes.recommendations || [])
          setModelVariant(recRes.model_variant)
        } catch (e) { console.error(e) }
      }
      setLoading(false)
    }
    load()
  }, [profileId])

  const handleClick = useCallback((movie, tmdbData) => {
    setSelectedMovie(movie)
    setSelectedTmdb(tmdbData || null)
  }, [])

  return (
    <div className="home-page" style={{ paddingTop: '80px' }}>
      <div className={`home-rows ${loading ? 'loading' : ''}`}>
        {recs.length > 0 && (
          <MovieRow title="Recommended Movies" movies={recs} onMovieClick={handleClick} showFeedback modelVariant={modelVariant} />
        )}
        <MovieRow title="Now Playing"     movies={nowPlaying} onMovieClick={handleClick} />
        <MovieRow title="Popular Movies"  movies={popular}    onMovieClick={handleClick} />
        <MovieRow title="Top Rated"       movies={topRated}   onMovieClick={handleClick} />
      </div>
      {selectedMovie && (
        <MovieModal
          movie={selectedMovie}
          tmdbData={selectedTmdb}
          onClose={() => { setSelectedMovie(null); setSelectedTmdb(null) }}
        />
      )}
    </div>
  )
}
