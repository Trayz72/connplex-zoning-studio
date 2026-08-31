import React from 'react';
import { AreaSeatChart } from '../../types/zoning';

interface AreaSeatChartPanelProps {
  chart?: AreaSeatChart;
}

const cellStyle: React.CSSProperties = { padding: '4px 6px', textAlign: 'right', whiteSpace: 'nowrap' };
const labelCellStyle: React.CSSProperties = { padding: '4px 6px', textAlign: 'left' };

export const AreaSeatChartPanel: React.FC<AreaSeatChartPanelProps> = ({ chart }) => {
  if (!chart) {
    return (
      <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '14px 16px', marginBottom: '16px', fontSize: '0.72rem', color: '#8b949e' }}>
        No Area &amp; Seat Chart available for this floor yet.
      </div>
    );
  }

  return (
    <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '14px 16px', marginBottom: '16px' }}>
      <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#8b949e', textTransform: 'uppercase', marginBottom: '8px' }}>
        Area &amp; Seat Chart (M8)
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.68rem', color: '#f0f6fc' }}>
          <thead>
            <tr style={{ color: '#8b949e', borderBottom: '1px solid #30363d' }}>
              <th style={labelCellStyle}>LOCATION</th>
              <th style={cellStyle}>AREA (sqft)</th>
              <th style={cellStyle}>LOUNGER</th>
              <th style={cellStyle}>SOFA SLIDER</th>
              <th style={cellStyle}>DUO LOUNGER</th>
              <th style={cellStyle}>PREMIUM RECLINER</th>
              <th style={cellStyle}>TOTAL SEATS</th>
            </tr>
          </thead>
          <tbody>
            {chart.screen_rows.map((row) => (
              <tr key={row.location} style={{ borderBottom: '1px solid #21262d' }}>
                <td style={labelCellStyle}>{row.location}</td>
                <td style={cellStyle}>{row.area_sqft}</td>
                <td style={cellStyle}>{row.lounger}</td>
                <td style={cellStyle}>{row.sofa_slider}</td>
                <td style={cellStyle}>{row.duo_lounger}</td>
                <td style={cellStyle}>{row.premium_recliner}</td>
                <td style={cellStyle}>{row.total_seats}</td>
              </tr>
            ))}
            <tr style={{ borderBottom: '1px solid #30363d', fontWeight: 700, background: 'rgba(56,139,253,0.06)' }}>
              <td style={labelCellStyle}>{chart.total_screen_row.location}</td>
              <td style={cellStyle}>{chart.total_screen_row.area_sqft}</td>
              <td style={cellStyle}>{chart.total_screen_row.lounger}</td>
              <td style={cellStyle}>{chart.total_screen_row.sofa_slider}</td>
              <td style={cellStyle}>{chart.total_screen_row.duo_lounger}</td>
              <td style={cellStyle}>{chart.total_screen_row.premium_recliner}</td>
              <td style={cellStyle}>{chart.total_screen_row.total_seats}</td>
            </tr>
            <tr style={{ color: '#8b949e' }}>
              <td style={labelCellStyle}>{chart.foyer_row.location}</td>
              <td style={cellStyle}>{chart.foyer_row.area_sqft}</td>
              <td style={cellStyle}>—</td><td style={cellStyle}>—</td><td style={cellStyle}>—</td><td style={cellStyle}>—</td><td style={cellStyle}>—</td>
            </tr>
            <tr style={{ color: '#8b949e', borderBottom: '1px solid #30363d' }}>
              <td style={labelCellStyle}>{chart.exit_passage_row.location}</td>
              <td style={cellStyle}>{chart.exit_passage_row.area_sqft}</td>
              <td style={cellStyle}>—</td><td style={cellStyle}>—</td><td style={cellStyle}>—</td><td style={cellStyle}>—</td><td style={cellStyle}>—</td>
            </tr>
            <tr style={{ fontWeight: 800, color: '#3fb950' }}>
              <td style={labelCellStyle}>{chart.grand_total_row.location}</td>
              <td style={cellStyle}>{chart.grand_total_row.area_sqft}</td>
              <td style={cellStyle}>{chart.grand_total_row.lounger}</td>
              <td style={cellStyle}>{chart.grand_total_row.sofa_slider}</td>
              <td style={cellStyle}>{chart.grand_total_row.duo_lounger}</td>
              <td style={cellStyle}>{chart.grand_total_row.premium_recliner}</td>
              <td style={cellStyle}>{chart.grand_total_row.total_seats}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: '0.62rem', color: '#8b949e', marginTop: '8px', lineHeight: 1.4 }}>
        {chart.foyer_row.note}
      </div>
    </div>
  );
};
