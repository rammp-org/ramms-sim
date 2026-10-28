// RammsBridgeSubsystem.h
#pragma once
#include "Subsystems/EngineSubsystem.h"
#include "RammsBridgeSubsystem.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnRammsPanelJson, const FString&, PanelJson);

UCLASS()
class URammsBridgeSubsystem : public UEngineSubsystem
{
	GENERATED_BODY()
public:
	UPROPERTY(BlueprintAssignable, Category = "Ramms Bridge")
	FOnRammsPanelJson OnPanelJson;

	UFUNCTION(BlueprintCallable, Category = "Ramms Bridge")
	void BroadcastPanelJson(const FString& PanelJson) { OnPanelJson.Broadcast(PanelJson); }
};