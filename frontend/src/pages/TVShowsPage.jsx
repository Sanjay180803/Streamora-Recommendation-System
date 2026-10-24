import { useState, useEffect, useCallback } from 'react'
import { getTMDBPopularTV, getTMDBOnAirTV, getTMDBTopRatedTV, tvToMovie } from '../api/client'
import MovieRow from '../components/MovieRow'
import MovieModal from '../components/MovieModal'
import './HomePage.css'

export default function TVShowsPage() {
  const [popular, setPopular]     = useState([])
  const [onAir, setOnAir]         = useState([])
  const [topRated, setTopRated]   = useState([])
  const [selectedMovie, setSelectedMovie] = useState(null)
  const [selectedTmdb, setSelectedTmdb]   = useState(null)
  const [loading, setLoading]     = useState(true)

  useEffect(() => {
    const load = async () => {
      const [pop, air, top] = await Promise.all([
        getTMDBPopularTV(),
        getTMDBOnAirTV(),
        getTMDBTopRatedTV(),
      ])
      setPopular(pop.map(tvToMovie))
      setOnAir(air.map(tvToMovie))
      setTopRated(top.map(tvToMovie))
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
        <MovieRow title="Popular TV Shows"    movies={popular}   onMovieClick={handleClick} />
        <MovieRow title="Currently On Air"    movies={onAir}     onMovieClick={handleClick} />
        <MovieRow title="Top Rated Series"    movies={topRated}  onMovieClick={handleClick} />
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
