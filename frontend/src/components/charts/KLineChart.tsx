import React, { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'
import type { DailyQuote } from '@/types'

interface KLineChartProps {
  data: DailyQuote[]
  height?: number
}

const KLineChart: React.FC<KLineChartProps> = ({ data, height = 380 }) => {
  const chartRef = useRef<HTMLDivElement>(null)
  const instanceRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!chartRef.current) return
    instanceRef.current = echarts.init(chartRef.current, 'dark')
    return () => instanceRef.current?.dispose()
  }, [])

  useEffect(() => {
    if (!instanceRef.current || !data.length) return

    const sorted = [...data].sort((a, b) => a.trade_date.localeCompare(b.trade_date))
    const dates = sorted.map(d => d.trade_date)
    // [open, close, low, high]
    const candleData = sorted.map(d => [d.open, d.close, d.low, d.high])
    const volumes = sorted.map(d => ({
      value: d.volume ?? 0,
      itemStyle: { color: (d.close ?? 0) >= (d.open ?? 0) ? '#ff4d4d' : '#26a95b' },
    }))

    const option: EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#1e2538',
        borderColor: '#2d3561',
        textStyle: { color: '#e8eaf0', fontFamily: 'DM Mono', fontSize: 12 },
        axisPointer: { type: 'cross' },
      },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [
        { left: 60, right: 20, top: 20, bottom: 120, height: '60%' },
        { left: 60, right: 20, bottom: 40, height: '20%' },
      ],
      xAxis: [
        {
          type: 'category',
          data: dates,
          gridIndex: 0,
          axisLabel: { show: false },
          axisLine: { lineStyle: { color: '#2d3561' } },
          boundaryGap: false,
        },
        {
          type: 'category',
          data: dates,
          gridIndex: 1,
          axisLabel: { color: '#8892b0', fontSize: 10 },
          axisLine: { lineStyle: { color: '#2d3561' } },
          boundaryGap: false,
        },
      ],
      yAxis: [
        {
          scale: true,
          gridIndex: 0,
          axisLabel: { color: '#8892b0', fontSize: 11, fontFamily: 'DM Mono' },
          axisLine: { show: false },
          splitLine: { lineStyle: { color: '#2d3561', type: 'dashed' } },
        },
        {
          scale: true,
          gridIndex: 1,
          axisLabel: { color: '#8892b0', fontSize: 10, fontFamily: 'DM Mono' },
          axisLine: { show: false },
          splitLine: { show: false },
        },
      ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 1],
          start: Math.max(0, 100 - (120 / data.length) * 100),
          end: 100,
        },
        {
          show: true,
          xAxisIndex: [0, 1],
          type: 'slider',
          bottom: 5,
          start: Math.max(0, 100 - (120 / data.length) * 100),
          end: 100,
          height: 22,
          handleStyle: { color: '#00d4aa' },
          textStyle: { color: '#8892b0' },
          dataBackground: { lineStyle: { color: '#2d3561' }, areaStyle: { color: '#2d3561' } },
        },
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: candleData,
          itemStyle: {
            color: '#ff4d4d',
            color0: '#26a95b',
            borderColor: '#ff4d4d',
            borderColor0: '#26a95b',
          },
        },
        {
          name: '成交量',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes,
          barMaxWidth: 6,
        },
      ],
    }

    instanceRef.current.setOption(option, true)
  }, [data])

  useEffect(() => {
    const handleResize = () => instanceRef.current?.resize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  return <div ref={chartRef} style={{ height }} className="w-full" />
}

export default KLineChart
