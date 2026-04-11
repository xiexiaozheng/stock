import React, { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

interface ValuationChartProps {
  data: Array<{ trade_date: string; pe_ttm?: number; pb?: number }>
  metric?: 'pe_ttm' | 'pb'
  quantiles?: Record<string, number>
  height?: number
}

const ValuationChart: React.FC<ValuationChartProps> = ({
  data,
  metric = 'pe_ttm',
  quantiles = {},
  height = 300,
}) => {
  const chartRef = useRef<HTMLDivElement>(null)
  const instanceRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!chartRef.current) return
    instanceRef.current = echarts.init(chartRef.current, 'dark')
    return () => instanceRef.current?.dispose()
  }, [])

  useEffect(() => {
    if (!instanceRef.current || !data.length) return

    const dates = data.map(d => d.trade_date)
    const values = data.map(d => (d[metric] !== undefined ? d[metric] : null))
    const label = metric === 'pe_ttm' ? 'PE-TTM' : 'PB'

    const markLineData: Array<{ yAxis: number; name: string; lineStyle: Record<string, unknown>; label: Record<string, unknown> }> = []
    const qColors: Record<string, string> = { p25: '#f59e0b', p50: '#00d4aa', p75: '#ff4d4d' }
    for (const [key, val] of Object.entries(quantiles)) {
      markLineData.push({
        yAxis: val,
        name: key.toUpperCase(),
        lineStyle: { color: qColors[key] ?? '#888', type: 'dashed' },
        label: { formatter: `${key.toUpperCase()}: ${val.toFixed(1)}`, color: qColors[key] ?? '#888' },
      })
    }

    const option: EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#1e2538',
        borderColor: '#2d3561',
        textStyle: { color: '#e8eaf0', fontFamily: 'DM Mono' },
      },
      grid: { left: 60, right: 20, top: 30, bottom: 50 },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#2d3561' } },
        axisLabel: { color: '#8892b0', fontSize: 11 },
        boundaryGap: false,
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        splitLine: { lineStyle: { color: '#2d3561', type: 'dashed' } },
        axisLabel: { color: '#8892b0', fontSize: 11, fontFamily: 'DM Mono' },
      },
      series: [
        {
          name: label,
          type: 'line',
          data: values,
          smooth: false,
          symbol: 'none',
          lineStyle: { color: '#00d4aa', width: 1.5 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(0,212,170,0.2)' },
              { offset: 1, color: 'rgba(0,212,170,0.02)' },
            ]),
          },
          markLine: markLineData.length
            ? {
                silent: true,
                data: markLineData.map(m => ({ ...m })),
              }
            : undefined,
        },
      ],
    }

    instanceRef.current.setOption(option, true)
  }, [data, metric, quantiles])

  useEffect(() => {
    const handleResize = () => instanceRef.current?.resize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  return <div ref={chartRef} style={{ height }} className="w-full" />
}

export default ValuationChart
