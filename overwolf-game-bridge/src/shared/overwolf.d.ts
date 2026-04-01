export type OverwolfGameInfo = {
  classId?: number;
  title?: string;
  isRunning?: boolean;
};

type SetRequiredFeaturesResult = {
  success: boolean;
  supportedFeatures: string[];
};

type Listener<T> = {
  addListener(callback: (payload: T) => void): void;
  removeListener(callback: (payload: T) => void): void;
};

type OverwolfEventEnvelope = {
  feature?: string;
  category?: string;
  key?: string;
  value?: unknown;
  info?: Record<string, unknown>;
};

type OverwolfNewEvent = {
  name: string;
  data?: unknown;
};

type OverwolfNewEventsEnvelope = {
  events?: OverwolfNewEvent[];
};

declare global {
  interface Window {
    overwolf?: {
      games: {
        getRunningGameInfo(callback: (info: OverwolfGameInfo) => void): void;
        onGameInfoUpdated: Listener<{ gameInfo?: OverwolfGameInfo }>;
        events: {
          setRequiredFeatures(features: string[], callback: (result: SetRequiredFeaturesResult) => void): void;
          getInfo(callback: (info: unknown) => void): void;
          onInfoUpdates2: Listener<OverwolfEventEnvelope>;
          onNewEvents: Listener<OverwolfNewEventsEnvelope | OverwolfNewEvent>;
          onError: Listener<{ reason?: string; message?: string }>;
        };
      };
    };
  }
}

export {};
