// Additive saved-state evidence. Immutable recordings remain untouched.
import {decodeScreen, glyph} from './home-watch-model.mjs';
const integer = value => Number.isSafeInteger(value) && value >= 0;
const hash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const identity = value => typeof value === 'string' && /^[a-z0-9-]{1,100}$/.test(value);
const evidence = value => value && Object.keys(value).sort().join(',') === 'sha256,url'
  && hash(value.sha256) && typeof value.url === 'string'
  && /^https:\/\/github\.com\/lemoz\/fort-gym\/blob\/[a-f0-9]{40}\/experiments\/evidence\/[a-z0-9_]+\.json$/.test(value.url);
const metrics = ['population','recorded_dead_citizens','completed_beds',
  'completed_workshops','completed_farms','food_stock','drink_stock'];
const fields = ['recording_id','recording_sha256','source_recording_id','campaign_id',
  'source_revision','model','reasoning_effort','control_profile','saved_decision',
  'saved_elapsed_ticks','saved_year','saved_year_tick','origin_year','origin_year_tick',
  'ticks_per_year','total_responses','total_tokens',
  'reported_model_charge_usd','saved_metrics','checkpoint_sha256','native_audit_sha256',
  'fresh_reload_verified','human_gameplay_rescue','functioning_assessment',
  'sustainability_proven','result','review'];

function validInventoryScope(value) {
  const scope=value.inventory_scope;
  if (scope === undefined) return !['operating_with_workshop_development',
    'operating_with_incident_recovery'].includes(value.functioning_assessment);
  return scope && typeof scope === 'object' && !Array.isArray(scope)
    && Object.keys(scope).sort().join(',') === ['schema_version','food_trader_flagged_units',
      'food_nontrader_units','food_nontrader_start_units','drink_trader_flagged_units',
      'ownership_and_accessibility_proven'].sort().join(',')
    && scope.schema_version === 'fortgym.watch-inventory-scope/v1'
    && ['food_trader_flagged_units','food_nontrader_units','food_nontrader_start_units']
      .every(key=>integer(scope[key]))
    && scope.food_trader_flagged_units + scope.food_nontrader_units === value.saved_metrics?.food_stock
    && scope.drink_trader_flagged_units === null
    && scope.ownership_and_accessibility_proven === false;
}

function validIncidentRecovery(value, recording) {
  const incident=value.incident_recovery;
  if (incident === undefined) return value.functioning_assessment !== 'operating_with_incident_recovery';
  if (!incident || value.functioning_assessment !== 'operating_with_incident_recovery'
      || Object.keys(incident).sort().join(',') !== 'announcement,before_decision,kind,schema_version'
      || incident.schema_version !== 'fortgym.watch-incident-recovery/v1'
      || incident.kind !== 'ghost_put_to_rest' || !integer(incident.before_decision)
      || typeof incident.announcement !== 'string'
      || !/^[^\r\n]{1,80}, Ghostly [^\r\n]{1,40} has been put to rest\.$/.test(incident.announcement)) return false;
  const frame=recording.frames.find(frame=>frame.decision===incident.before_decision);
  if (!frame) return false;
  const {width,height}=frame.screen, tiles=decodeScreen(frame.screen);
  return Array.from({length:height},(_,y)=>Array.from({length:width},(_,x)=>
    glyph(tiles[x*height+y][0])).join('')).some(line=>line.includes(incident.announcement));
}

export function validateSavedOutcomes(data) {
  if (!data || data.schema_version !== 'fortgym.watch-saved-outcomes/v1'
      || Object.keys(data).sort().join(',') !== 'outcomes,schema_version'
      || !Array.isArray(data.outcomes) || data.outcomes.length > 100
      || !data.outcomes.every(row => row && identity(row.recording_id))
      || new Set(data.outcomes.map(row => row.recording_id)).size !== data.outcomes.length) {
    throw Error('Invalid saved-outcome index');
  }
  return data;
}

export function savedOutcome(data, recording, catalog) {
  validateSavedOutcomes(data);
  const value = data.outcomes.find(row => row.recording_id === recording.id);
  if (!value) return null;
  const row = catalog.find(item => item.id === recording.id);
  const previous = catalog.find(item => item.id === value.source_recording_id);
  const endpoint = recording.frames.at(-1).after;
  const countFields = ['saved_decision','saved_elapsed_ticks','saved_year',
    'saved_year_tick','origin_year','origin_year_tick','ticks_per_year',
    'total_responses','total_tokens'];
  const expectedFields=[...fields, ...['inventory_scope','incident_recovery'].filter(key=>value[key]!==undefined)];
  if (Object.keys(value).sort().join(',') !== [...expectedFields].sort().join(',')
      || !validInventoryScope(value)
      || !validIncidentRecovery(value, recording)
      || !row || !previous || previous.id === row.id
      || !identity(value.campaign_id) || !identity(value.source_recording_id)
      || !hash(value.recording_sha256) || value.recording_sha256 !== row.sha256
      || !hash(value.checkpoint_sha256) || !hash(value.native_audit_sha256)
      || value.native_audit_sha256 !== recording.audit_sha256
      || !/^[a-f0-9]{40}$/.test(value.source_revision)
      || value.source_revision !== recording.source_revision
      || value.model !== recording.model || typeof value.model !== 'string'
      || value.model.length > 100 || value.reasoning_effort !== 'medium'
      || value.control_profile !== recording.control_profile
      || value.control_profile !== 'native_keyboard_bindings/v1'
      || !countFields.every(key => integer(value[key]))
      || value.saved_decision !== recording.saved_through_decision
      || value.saved_decision !== recording.last_decision
      || value.total_responses < value.saved_decision
      || previous.last_decision + 1 !== recording.first_decision
      || value.recording_id !== value.campaign_id + '-' + recording.first_decision + '-' + recording.last_decision
      || !previous.id.startsWith(value.campaign_id + '-')
      || previous.model !== recording.model || previous.control_profile !== recording.control_profile
      || previous.source_revision !== recording.source_revision
      || value.saved_year !== endpoint.year || value.saved_year_tick !== endpoint.tick
      || value.ticks_per_year !== 403200 || value.saved_year_tick >= value.ticks_per_year
      || value.origin_year_tick >= value.ticks_per_year
      || (value.saved_year - value.origin_year) * value.ticks_per_year
        + value.saved_year_tick - value.origin_year_tick !== value.saved_elapsed_ticks
      || value.fresh_reload_verified !== true || value.human_gameplay_rescue !== false
      || !['operating_but_fragile','operating_with_adaptive_supply_recovery','operating_with_workshop_development','operating_with_incident_recovery'].includes(value.functioning_assessment)
      || value.sustainability_proven !== false
      || value.saved_elapsed_ticks < 403200
      || value.reported_model_charge_usd !== null
      || !evidence(value.result) || !evidence(value.review)
      || !value.saved_metrics || Object.keys(value.saved_metrics).sort().join(',') !== [...metrics].sort().join(',')
      || !metrics.every(key => integer(value.saved_metrics[key]))
      || value.saved_metrics.population !== endpoint.population) {
    throw Error('Saved outcome differs from its recording');
  }
  return value;
}

export function savedOutcomeSummary(value) {
  const m = value.saved_metrics;
  const assessment = value.functioning_assessment === 'operating_with_adaptive_supply_recovery'
    ? 'Operating with adaptive supply recovery at this saved endpoint. Long-term sustainability remains unproven.'
    : value.functioning_assessment === 'operating_with_incident_recovery'
    ? 'Operating with incident recovery at this saved endpoint. Captured game announcement before decision '
      + value.incident_recovery.before_decision + ': “' + value.incident_recovery.announcement
      + '” Long-term sustainability remains unproven.'
    : value.functioning_assessment === 'operating_with_workshop_development'
    ? 'Operating with workshop development at this saved endpoint. Supply recovery and long-term sustainability remain unproven.'
    : 'Operating but fragile at this saved endpoint.';
  const i=value.inventory_scope;
  const inventory=i
    ? 'Recorded inventory: ' + i.food_nontrader_units + ' non-trader food units and '
      + i.food_trader_flagged_units + ' trader-flagged food units (' + m.food_stock + ' total). '
      + 'Non-trader food at the previous save: ' + i.food_nontrader_start_units + '. '
      + 'Drink inventory: ' + m.drink_stock + ' units. Drink ownership was not measured. '
      + 'These counts do not prove accessible fortress supplies. '
    : 'Supplies: ' + m.food_stock + ' food units and ' + m.drink_stock + ' drinks. ';
  return value.model + ' · Medium · standard keyboard input. '
    + (value.saved_elapsed_ticks / 403200).toFixed(3) + ' elapsed game years · '
    + (value.saved_elapsed_ticks - 403200).toLocaleString() + ' ticks into Year Two. '
    + m.population + ' living dwarves · ' + m.recorded_dead_citizens + ' recorded death'
    + (m.recorded_dead_citizens === 1 ? '' : 's') + ' · '
    + m.completed_beds + ' beds · ' + m.completed_workshops + ' workshops · '
    + m.completed_farms + ' farms. ' + inventory + 'Saved checkpoint ' + value.saved_decision
    + ' was verified in a fresh game process. ' + assessment;
}

export function savedOutcomeHistory(value, recording) {
  return 'Continued from checkpoint ' + (recording.first_decision - 1) + '. '
    + value.total_responses.toLocaleString() + ' cumulative responses and '
    + value.total_tokens.toLocaleString()
    + ' returned tokens. Subscription dollar charges were not reported. '
    + 'This is the same campaign, not an independent trial.';
}
