import { useState, useCallback } from 'react'
import { useAuth } from '../context/AuthContext'
import MovieRow from '../components/MovieRow'
import MovieModal from '../components/MovieModal'
import './HomePage.css'

export default function MyListPage() {
  const { watchHistory } = useAuth()
  const [selectedMovie, setSelectedMovie] = useState(null)
  const [selectedTmdb, setSelectedTmdb]   = useState(null)

  // Watch history as movie cards
  const watchedList = watchHistory.map(item => ({
    item_id: item.title?.toLowerCase().replace(/\s+/g, '_') || item,
    item_idx: -1,
    title: item.title || item,
    release_year: item.release_year || null,
    genres: item.genres || [],
    log_popularity: 0,
  }))

  const handleClick = useCallback((movie, tmdbData) => {
    setSelectedMovie(movie)
    setSelectedTmdb(tmdbData || null)
  }, [])

  return (
    <div className="home-page" style={{ paddingTop: '80px' }}>
      <div className="home-rows">
        {watchedList.length > 0 ? (
          <MovieRow
            title="My Watch History"
            movies={watchedList}
            onMovieClick={handleClick}
          />
        ) : (
          <div style={{ padding: '120px 4%', color: '#888', fontSize: '18px' }}>
            You haven't watched anything yet. Start watching to build your list.
          </div>
        )}
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
