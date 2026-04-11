import React from 'react'

interface MetricCardProps {
  label: string
  value?: number | string | null
  unit?: string
  subtext?: string
  highlight?: boolean
  percentile?: number
}

const MetricCard: React.FC<MetricCardProps> = ({ label, value, unit, subtext, highlight, percentile }) => {
  return (
    <div className={`card ${highlight ? 'border-accent/30' : ''}`}>
      <div className="text-xs text-text-secondary mb-1">{label}</div>
      <div className="flex items-baseline gap-1">
        <span className={`text-xl font-mono font-medium ${highlight ? 'text-accent' : 'text-text-primary'}`}>
          {value !== undefined && value !== null ? value : '-'}
        </span>
        {unit && <span className="text-xs text-text-secondary">{unit}</span>}
      </div>
      {subtext && <div className="text-xs text-text-muted mt-1">{subtext}</div>}
      {percentile !== undefined && percentile !== null && (
        <div className="mt-2">
          <div className="flex justify-between text-xs text-text-secondary mb-1">
            <span>历史分位</span>
            <span className="font-mono">{percentile.toFixed(0)}%</span>
          </div>
          <div className="h-1.5 bg-bg-secondary rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${percentile}%`,
                backgroundColor: percentile < 25 ? '#26a95b' : percentile > 75 ? '#ff4d4d' : '#00d4aa',
              }}
            />
          </div>
        </div>
      )}
    </div>
  )
}

export default MetricCard
