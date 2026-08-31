import React from 'react';
import { FeasibilityData } from '../../types/zoning';

interface ValidationPanelProps {
  hasReviewRequired?: boolean;
  feasibility?: FeasibilityData;
}

const RESULT_COLOR: Record<string, string> = {
  PASS: '#3fb950',
  FAIL: '#f85149',
  INSUFFICIENT_DATA: '#8b949e'
};

const RESULT_ICON: Record<string, string> = {
  PASS: '✓',
  FAIL: '✕',
  INSUFFICIENT_DATA: '?'
};

const OVERALL_COLOR: Record<string, string> = {
  FEASIBLE: '#3fb950',
  CONDITIONALLY_FEASIBLE: '#d29922',
  NOT_FEASIBLE: '#f85149',
  INSUFFICIENT_DATA: '#8b949e'
};

export const ValidationPanel: React.FC<ValidationPanelProps> = ({ hasReviewRequired = false, feasibility }) => {
  return (
    <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: '8px', padding: '14px 16px', marginBottom: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
        <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#8b949e', textTransform: 'uppercase' }}>
          Feasibility / Compliance Engine (M8)
        </div>
        {feasibility && (
          <span style={{
            fontSize: '0.65rem', fontWeight: 700, padding: '2px 6px', borderRadius: '4px',
            color: OVERALL_COLOR[feasibility.feasibility_result] || '#8b949e',
            border: `1px solid ${OVERALL_COLOR[feasibility.feasibility_result] || '#30363d'}`
          }}>
            {feasibility.feasibility_result.replace(/_/g, ' ')}
          </span>
        )}
      </div>

      {!feasibility && (
        <div style={{ fontSize: '0.72rem', color: '#8b949e' }}>
          No feasibility dataset loaded for this region.
        </div>
      )}

      {feasibility?.reason && (
        <div style={{ fontSize: '0.72rem', color: '#8b949e', fontStyle: 'italic' }}>{feasibility.reason}</div>
      )}

      {feasibility && feasibility.rule_results.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
          {feasibility.rule_results.map((rr) => (
            <div key={rr.rule_id} style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', fontSize: '0.72rem', padding: '3px 0', gap: '8px' }}>
              <span style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', color: '#f0f6fc' }}>
                <span style={{ color: RESULT_COLOR[rr.result], fontWeight: 700 }}>
                  {RESULT_ICON[rr.result]}
                </span>
                <span>
                  {rr.message}
                  {rr.measured_value !== null && (
                    <span style={{ color: '#8b949e' }}> ({rr.measured_value}{rr.unit ? ` ${rr.unit}` : ''} vs {rr.threshold}{rr.unit ? ` ${rr.unit}` : ''})</span>
                  )}
                </span>
              </span>
              <span style={{ color: '#8b949e', fontSize: '0.62rem', whiteSpace: 'nowrap', flexShrink: 0 }}>
                {rr.severity} · {rr.source}
              </span>
            </div>
          ))}
        </div>
      )}

      {hasReviewRequired && (
        <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid #30363d', fontSize: '0.72rem', color: '#d29922', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>⚠</span>
          <span><strong>Notice:</strong> Fourth floor requires architect on-site field verification for partition linework.</span>
        </div>
      )}
    </div>
  );
};
