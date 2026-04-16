function out = tc_prob_jma_windfield_scs_from_txt()
% 目标：基于 JMA bst_all.txt，计算风圈影响概率，并限定"进入中国南海海域"的台风
% - 风圈：JMA 30kt/50kt（椭圆：dir + long/short 半径，nm）
% - 限定样本：台风中心轨迹进入南海多边形（SCS）
% - 影响判定：目标点半径R区域(中心+圆周采样点) 任一点落入风圈椭圆 => 命中
% - "只在南海范围内评价"：仅用 台风中心位于SCS 的时刻 进行影响判定（口径B）
%
% 输出：
%   out.summary：包含条件概率 p(impact|enterSCS) 和绝对概率 p(impact & enterSCS)
%   out.perStorm：每个进入SCS台风是否命中
%   out.hitsByYear：按年命中次数（进入SCS样本内）SCS - South China Sea

%% ================== 0) 用户参数 ==================
bstTxtPath = fullfile(pwd, "bst_all.txt");

% 目标区域
lat0 = 20.9339;
lon0 = 112.202;
R_km = 100;          % R=0 表示只看点是否被风圈覆盖

% 时间窗口
yearRange = [1976, 2025];
months = 1:12;

% 风圈阈值（JMA）
windThreshold = 50;  % 30 or 50

% 目标区域采样密度
nBoundary = 72;      % 圆周采样点数：36~144

% ========== 南海范围（默认：矩形框，可按你项目定义改为更精细多边形）==========
% 常见工程近似：SCS ~ 0–25N, 105–121E（你可按需要收紧，例如到 3–23N 等）
scs_poly_lon = [105 121 121 105 105];
scs_poly_lat = [  0   0  25  25   0];
% ==========================================================================

outDir = fullfile(pwd, "out_tc_prob_scs");
%% =============================================================

assert(exist(bstTxtPath,'file')==2, "找不到 bst_all.txt：%s", bstTxtPath);
if ~exist(outDir,'dir'); mkdir(outDir); end
assert(ismember(windThreshold, [30,50]), "windThreshold 只能是 30 或 50");

%% Step 1) 解析 bst（含风圈字段）
T = read_jma_bst_all_with_radii(bstTxtPath);

%% Step 2) 时间转换：yymmddhh(数值) -> 8位字符串 -> datetime(UTC) + 显式世纪
tstr = arrayfun(@(x) sprintf('%08d', x), T.yymmddhh, 'UniformOutput', false);
tstr = string(tstr);
t = datetime(tstr, 'InputFormat', 'yyMMddHH', 'TimeZone', 'UTC');

yy = str2double(extractBetween(tstr, 1, 2));
t.Year(yy >= 51) = 1900 + yy(yy >= 51);
t.Year(yy <= 50) = 2000 + yy(yy <= 50);
T.time = t;

%% Step 3) 时间窗口筛选
T = T(year(T.time) >= yearRange(1) & year(T.time) <= yearRange(2), :);
T = T(ismember(month(T.time), months), :);

% 全样本 storm 列表
stormIDs_all = unique(T.storm_id);
nStorm_all = numel(stormIDs_all);
if nStorm_all == 0
    error("筛选后没有任何台风样本。请检查 yearRange/months。");
end

%% Step 4) 先判定：哪些台风"进入南海"（口径A：中心点进入多边形）
enterSCS = false(nStorm_all,1);

for i = 1:nStorm_all
    sid = stormIDs_all(i);
    Ts = T(T.storm_id == sid, :);

    % 注意 inpolygon 输入：x=lon, y=lat
    inSCS = inpolygon(Ts.lon, Ts.lat, scs_poly_lon, scs_poly_lat);
    enterSCS(i) = any(inSCS);
end

stormIDs_scs = stormIDs_all(enterSCS);
nStorm_scs = numel(stormIDs_scs);

if nStorm_scs == 0
    error("在该时间窗口内，没有任何台风中心进入你定义的南海多边形。请检查 scs_poly 或时间窗口。");
end

%% Step 5) 生成目标区域采样点（中心+圆周）
[latS, lonS] = make_circle_samples(lat0, lon0, R_km, nBoundary);

%% Step 6) 计算：在"进入南海"的台风中，影响概率（口径B：只用中心位于SCS的时刻来判定）
hit_scs = false(nStorm_scs,1);
minCenterDist_km = nan(nStorm_scs,1);
firstHitTime = repmat(datetime(NaT,'TimeZone','UTC'), nStorm_scs, 1);

for i = 1:nStorm_scs
    sid = stormIDs_scs(i);
    Ts = T(T.storm_id == sid, :);
    Ts = sortrows(Ts, 'time');

    % 中心最小距离（参考）
    minCenterDist_km(i) = min(haversine_km(Ts.lat, Ts.lon, lat0, lon0));

    % 仅保留"中心在南海"的时刻（这就是"只在南海范围内评价"）
    inSCS = inpolygon(Ts.lon, Ts.lat, scs_poly_lon, scs_poly_lat);
    Ts = Ts(inSCS, :);

    if isempty(Ts)
        % 理论上不应发生，因为此台风已满足 enterSCS，但为了稳健仍保留
        continue;
    end

    isHit = false;
    hitTime = datetime(NaT,'TimeZone','UTC');

    for k = 1:height(Ts)
        if windThreshold == 50
            dirCode  = Ts.dir50(k);
            rLong_nm = Ts.r50_long_nm(k);
            rShort_nm= Ts.r50_short_nm(k);
        else
            dirCode  = Ts.dir30(k);
            rLong_nm = Ts.r30_long_nm(k);
            rShort_nm= Ts.r30_short_nm(k);
        end

        if ~(isfinite(rLong_nm) && rLong_nm > 0)
            continue;
        end

        a_km = rLong_nm * 1.852;
        b_km = rShort_nm * 1.852;

        phi_deg = dircode_to_bearing_deg(dirCode);
        if isnan(phi_deg); phi_deg = 0; end
        if round(dirCode) == 9
            b_km = a_km; % 对称圆
        end

        if any(points_inside_wind_ellipse(latS, lonS, Ts.lat(k), Ts.lon(k), a_km, b_km, phi_deg))
            isHit = true;
            hitTime = Ts.time(k);
            break;
        end
    end

    hit_scs(i) = isHit;
    firstHitTime(i) = hitTime;
end

%% Step 7) 输出两个概率口径
nHit_scs = sum(hit_scs);

% 条件概率：只在进入SCS样本内
p_cond = nHit_scs / nStorm_scs;  % p(impact | enterSCS)

% 绝对概率：在所有台风样本里同时满足 enterSCS & impact
p_abs = nHit_scs / nStorm_all;   % p(impact & enterSCS)（注：impact 这里按口径B）

%% Step 8) 年发生概率（基于进入SCS样本内的命中次数）
hitStormIDs = stormIDs_scs(hit_scs);
hitYears = zeros(numel(hitStormIDs),1);
for j = 1:numel(hitStormIDs)
    sid = hitStormIDs(j);
    Tsj = T(T.storm_id == sid, :);
    hitYears(j) = year(min(Tsj.time));
end
yrs = yearRange(1):yearRange(2);
hitsByYear = arrayfun(@(yy) sum(hitYears==yy), yrs);
lambda = sum(hitsByYear) / numel(yrs);
p_year = 1 - exp(-lambda);

%% 打印结果
fprintf("=====================================\n");
fprintf("JMA wind-radii impact probability with SCS constraint\n");
fprintf("Target center (%.3f, %.3f), region R = %.1f km\n", lat0, lon0, R_km);
fprintf("Window: %d-%d, months=%s\n", yearRange(1), yearRange(2), mat2str(months));
fprintf("Wind threshold: %d kt (JMA)\n", windThreshold);
fprintf("All storms N_all = %d\n", nStorm_all);
fprintf("Enter SCS  N_scs = %d\n", nStorm_scs);
fprintf("Hit within SCS-evaluated times N_hit = %d\n", nHit_scs);
fprintf("Conditional p(impact | enterSCS) = %.4f (%.2f%%)\n", p_cond, 100*p_cond);
fprintf("Absolute     p(impact & enterSCS)= %.4f (%.2f%%)\n", p_abs, 100*p_abs);
fprintf("lambda = %.3f /year, p_year = %.4f (%.2f%%)\n", lambda, p_year, 100*p_year);
fprintf("=====================================\n");

%% 输出
out.summary = table(lat0, lon0, R_km, yearRange(1), yearRange(2), string(mat2str(months)), ...
    windThreshold, nStorm_all, nStorm_scs, nHit_scs, p_cond, p_abs, lambda, p_year, ...
    'VariableNames', {'lat0','lon0','R_km','year_start','year_end','months',...
    'windThreshold_kt','N_all','N_enterSCS','N_hit','p_cond_impact_given_SCS','p_abs_impact_and_SCS',...
    'lambda_per_year','p_year'});

out.perStorm = table(stormIDs_scs, hit_scs, minCenterDist_km, firstHitTime, ...
    'VariableNames', {'storm_id','hit','minCenterDist_km','firstHitTime_utc'});

out.hitsByYear = table(yrs(:), hitsByYear(:), 'VariableNames', {'year','hit_storms'});

writetable(out.summary,  fullfile(outDir, "summary.csv"));
writetable(out.perStorm, fullfile(outDir, "per_storm.csv"));
writetable(out.hitsByYear, fullfile(outDir, "hits_by_year.csv"));

end

%% ======================= 解析函数（适配你贴的格式） =======================
function T = read_jma_bst_all_with_radii(bstTxt)
fid = fopen(bstTxt, 'r');
assert(fid>0, "Cannot open: %s", bstTxt);

storm_id = [];
yymmddhh = [];
lat = []; lon = [];
pres = []; wind = [];
grade = [];

dir50 = []; r50L = []; r50S = [];
dir30 = []; r30L = []; r30S = [];

curID = NaN; remain = 0;

while ~feof(fid)
    line = fgetl(fid);
    if ~ischar(line) || strlength(string(line))==0
        continue;
    end

    if startsWith(line, "66666")
        numsH = sscanf(line, "%f");
        if numel(numsH) >= 3
            curID = numsH(2);
            remain = numsH(3);
        else
            curID = NaN; remain = 0;
        end
        continue;
    end

    if isnan(curID) || remain <= 0
        continue;
    end

    nums = sscanf(line, "%f");
    if numel(nums) >= 7
        t8 = nums(1);
        g  = nums(3);
        la = nums(4) * 0.1;
        lo = nums(5) * 0.1;
        pr = nums(6);
        wi = nums(7);

        d50 = 0; L50 = 0; S50 = 0;
        d30 = 0; L30 = 0; S30 = 0;

        if numel(nums) >= 11
            A50 = nums(8);  B50 = nums(9);
            A30 = nums(10); B30 = nums(11);

            [d50, L50] = split_dir_long(A50); S50 = round(B50);
            [d30, L30] = split_dir_long(A30); S30 = round(B30);
        end

        storm_id(end+1,1) = curID; %#ok<AGROW>
        yymmddhh(end+1,1) = t8;
        grade(end+1,1)    = g;
        lat(end+1,1)      = la;
        lon(end+1,1)      = lo;
        pres(end+1,1)     = pr;
        wind(end+1,1)     = wi;

        dir50(end+1,1) = d50; r50L(end+1,1) = L50; r50S(end+1,1) = S50;
        dir30(end+1,1) = d30; r30L(end+1,1) = L30; r30S(end+1,1) = S30;
    end

    remain = remain - 1;
end

fclose(fid);

T = table(storm_id, yymmddhh, grade, lat, lon, pres, wind, ...
          dir50, r50L, r50S, dir30, r30L, r30S, ...
    'VariableNames', {'storm_id','yymmddhh','grade','lat','lon','pres_hpa','wind_kt', ...
                      'dir50','r50_long_nm','r50_short_nm', ...
                      'dir30','r30_long_nm','r30_short_nm'});
end

function [dirCode, long_nm] = split_dir_long(A)
A = round(A);
dirCode = floor(A / 10000);
long_nm = mod(A, 10000);
end

%% ======================= 区域采样 & 椭圆判定 =======================
function [latS, lonS] = make_circle_samples(lat0, lon0, R_km, nBoundary)
latS = lat0; lonS = lon0;
if R_km <= 0
    return;
end
az = linspace(0, 360, nBoundary+1); az(end) = [];
for i = 1:numel(az)
    [lat_i, lon_i] = destination_point(lat0, lon0, az(i), R_km);
    latS(end+1,1) = lat_i; %#ok<AGROW>
    lonS(end+1,1) = lon_i; %#ok<AGROW>
end
end

function inside = points_inside_wind_ellipse(latP, lonP, latC, lonC, a_km, b_km, phi_deg)
d = haversine_km(latP, lonP, latC, lonC);
alpha = bearing_deg(latC, lonC, latP, lonP);
theta = deg2rad(wrapTo360(alpha - phi_deg));

a = a_km; b = b_km;
r = (a*b) ./ sqrt( (b*cos(theta)).^2 + (a*sin(theta)).^2 );
inside = d <= r;
end

%% ======================= 球面工具 =======================
function dkm = haversine_km(lat1, lon1, lat2, lon2)
R = 6371.0;
lat1 = deg2rad(lat1); lon1 = deg2rad(lon1);
lat2 = deg2rad(lat2); lon2 = deg2rad(lon2);
dlat = lat2 - lat1;
dlon = lon2 - lon1;
a = sin(dlat/2).^2 + cos(lat1).*cos(lat2).*sin(dlon/2).^2;
dkm = 2*R*asin(sqrt(a));
end

function brng = bearing_deg(lat1, lon1, lat2, lon2)
lat1 = deg2rad(lat1); lon1 = deg2rad(lon1);
lat2 = deg2rad(lat2); lon2 = deg2rad(lon2);
dlon = lon2 - lon1;
x = sin(dlon).*cos(lat2);
y = cos(lat1).*sin(lat2) - sin(lat1).*cos(lat2).*cos(dlon);
brng = mod(rad2deg(atan2(x,y)) + 360, 360);
end

function phi = dircode_to_bearing_deg(code)
switch round(code)
    case 1, phi = 45;   % NE
    case 2, phi = 90;   % E
    case 3, phi = 135;  % SE
    case 4, phi = 180;  % S
    case 5, phi = 225;  % SW
    case 6, phi = 270;  % W
    case 7, phi = 315;  % NW
    case 8, phi = 0;    % N
    case 9, phi = 0;    % symmetric circle
    otherwise, phi = NaN;
end
end

function [lat2, lon2] = destination_point(lat1, lon1, az_deg, dist_km)
R = 6371.0;
lat1 = deg2rad(lat1); lon1 = deg2rad(lon1);
az = deg2rad(az_deg);
d = dist_km / R;

lat2 = asin( sin(lat1).*cos(d) + cos(lat1).*sin(d).*cos(az) );
lon2 = lon1 + atan2( sin(az).*sin(d).*cos(lat1), cos(d) - sin(lat1).*sin(lat2) );

lat2 = rad2deg(lat2);
lon2 = rad2deg(lon2);
lon2 = wrapTo180(lon2);
end