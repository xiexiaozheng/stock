import React, { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'
import type { Financial } from '@/types'

interface FinancialChartProps {
  data: Financial[]
  height?: number
}

const FinancialChart: React.FC<FinancialChartProps> = ({ data, height = 320 }) => {
  const chartRef = useRef<HTMLDivElement>(null)
  const instanceRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!chartRef.current) return
    instanceRef.current = echarts.init(chartRef.current, 'dark')
    return () => instanceRef.current?.dispose()
  }, [])

  useEffect(() => {
    if (!instanceRef.current || !data.length) return

    const sorted = [...data]
      .filter(d => d.report_type === 'annual')
      .sort((a, b) => a.report_date.localeCompare(b.report_date))

    const years = sorted.map(d => d.report_date.slice(0, 4))
    const revenues = sorted.map(d => d.operating_revenue ? d.operating_revenue / 1e8 : null)
    const profits = sorted.map(d => d.net_profit ? d.net_profit / 1e8 : null)
    const roes = sorted.map(d => d.roe ?? null)
    const grossMargins = sorted.map(d => d.gross_margin ?? null)

    const option: EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#1e2538',
        borderColor: '#2d3561',
        textStyle: { color: '#e8eaf0' },
        axisPointer: { type: 'shadow' },
      },
      legend: {
        data: ['营收(亿)', '净利润(亿)', 'ROE(%)', '毛利率(%)'],
        textStyle: { color: '#8892b0', fontSize: 12 },
        top: 5,
      },
      grid: { left: 55, right: 55, top: 50, bottom: 50 },
      xAxis: {
        type: 'category',
        data: years,
        axisLabel: { color: '#8892b0', fontSize: 11 },
        axisLine: { lineStyle: { color: '#2d3561' } },
      },
      yAxis: [
        {
          type: 'value',
          name: '亿元',
          nameTextStyle: { color: '#8892b0' },
          axisLabel: { color: '#8892b0', fontSize: 11, fontFamily: 'DM Mono' },
          axisLine: { show: false },
          splitLine: { lineStyle: { color: '#2d3561', type: 'dashed' } },
        },
        {
          type: 'value',
          name: '%',
          nameTextStyle: { color: '#8892b0' },
          axisLabel: { color: '#8892b0', fontSize: 11, fontFamily: 'DM Mono' },
          axisLine: { show: false },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '营收(亿)',
          type: 'bar',
          yAxisIndex: 0,
          data: revenues,
          itemStyle: { color: 'rgba(0,212,170,0.7)' },
          barMaxWidth: 32,
        },
        {
          name: '净利润(亿)',
          type: 'bar',
          yAxisIndex: 0,
          data: profits,
          itemStyle: { color: 'rgba(255,77,77,0.7)' },
          barMaxWidth: 32,
        },
        {
          name: 'ROE(%)',
          type: 'line',
          yAxisIndex: 1,
          data: roes,
          symbol: 'circle',
          symbolSize: 5,
          lineStyle: { color: '#f59e0b', width: 2 },
          itemStyle: { color: '#f59e0b' },
        },
        {
          name: '毛利率(%)',
          type: 'line',
          yAxisIndex: 1,
          data: grossMargins,
          symbol: 'circle',
          symbolSize: 5,
          lineStyle: { color: '#818cf8', width: 2 },
          itemStyle: { color: '#818cf8' },
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

export default FinancialChart
