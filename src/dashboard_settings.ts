import type {DashboardContent, Status} from './types';

export type DashboardRowChoice = NonNullable<Status['faceplate_player_city_dashboard_row']>;

/** One catalogue for Dashboard and City without a player count. */
export function dashboardRowOptions(game = true): {data: DashboardRowChoice; label: string}[] {
  return [
    {data:'next_hour',label:'Weather — Next hour'},
    {data:'today',label:'Weather — Today'},
    {data:'controllers',label:'Controllers'},
    ...(game ? [
      {data:'d' as const,label:'Achievement Progress'},
      {data:'c' as const,label:'Session + Controller'},
      {data:'b' as const,label:'Total Playtime + Achievements'},
      {data:'a' as const,label:'Session + Achievements + Battery'},
      {data:'e' as const,label:'Total Playtime + Achievements + Battery'},
    ] : []),
  ];
}

export function dashboardRowUsesControllers(choice: DashboardRowChoice) {
  return choice === 'controllers' || choice === 'a' || choice === 'c' || choice === 'e';
}

/** Preserve legacy Home/game content until that context is explicitly edited. */
export function dashboardContext(status: Status, context: 'home' | 'game'): DashboardContent {
  const session = context === 'game' && status.faceplate_dashboard_game_session;
  return {
    show_weather: status.faceplate_dashboard_show_weather,
    show_bottom_row: status.faceplate_dashboard_show_bottom_row ?? true,
    bottom_mode: session ? 'controllers' : status.faceplate_dashboard_bottom_mode,
    battery_style: status.faceplate_dashboard_battery_style,
    show_p2: status.faceplate_dashboard_show_p2,
    show_session: Boolean(session),
    game_row: 'existing',
    weather_position: 'right',
    ...status.faceplate_dashboard_contexts?.[context],
    ...(context === 'home' ? {show_session: false, game_row: 'existing' as const} : {}),
  };
}

export function updateDashboardContext(status: Status, context: 'home' | 'game', patch: Partial<DashboardContent>) {
  return {...status.faceplate_dashboard_contexts,
    [context]: {...dashboardContext(status, context), ...patch}};
}
