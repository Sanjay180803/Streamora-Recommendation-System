import { useState, useEffect, useCallback } from 'react'
import { getTMDBNowPlaying, getTMDBOnAirTV, getTMDBTrendingAll, movieToCard, tvToMovie } from '../api/client'
import MovieRow from '../components/MovieRow'
import MovieModal from '../components/MovieModal'
import './HomePage.css'

export default function NewPopularPage() {
  const [trending, setTrending]   = useState([])
  const [newMovies, setNewMovies] = useState([])
  const [newTV, setNewTV]         = useState([])
  const [selectedMovie, setSelectedMovie] = useState(null)
  const [selectedTmdb, setSelectedTmdb]   = useState(null)
  const [loading, setLoading]     = useState(true)

  useEffect(() => {
    const load = async () => {
      const [trend, movies, tv] = await Promise.all([
        getTMDBTrendingAll(),
        getTMDBNowPlaying(),
        getTMDBOnAirTV(),
      ])
      // Trending can be movies or TV — handle both
      setTrending(trend.map(t =>
        t.media_type === 'tv' ? tvToMovie(t) : movieToCard(t)
      ))
      setNewMovies(movies.map(movieToCard))
      setNewTV(tv.map(tvToMovie))
      setLoading(false)
    }
    load()
  }, [])

  const handleClick = useCallback((movie, tmdbData) => {
    setSelectedMovie(movie)
    setSelectedTmdb(tmdbData || null)
  }, [])

  return (
    <div className="home-page" style={{ paddingTop: '80px' }}>
      <div className={`home-rows ${loading ? 'loading' : ''}`}>
        <MovieRow title="Trending This Week" movies={trending}  onMovieClick={handleClick} />
        <MovieRow title="New Movies"         movies={newMovies} onMovieClick={handleClick} />
        <MovieRow title="New TV Shows"       movies={newTV}     onMovieClick={handleClick} />
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
